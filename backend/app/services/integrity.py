"""数据库级合排不变量触发器。

即使应用代码在事务中途出错，数据库也拒绝出现以下状态：
1. 合排方案（merge_key 非空）seated_count 必须 > 0 —— 禁止“合排方案没有座位”。
2. 同一 merge_key 至多覆盖两间考室 —— 禁止第三室搭车改动。
3. halls.merged_into 非空时，本室与主室的最新方案必须是同一 merge_key 且各有座位
   —— 禁止“留下合排指针却没有座位”，禁止单边指针，禁止两室批次不一致。
4. 已合排考室禁止再写入无 merge_key 的单室方案。

create_all 建完全部表后（MetaData.after_create）按方言自动安装：
SQLite（测试环境）与 PostgreSQL（生产）。
"""
from __future__ import annotations

from sqlalchemy import event, text

from app.database import Base

_MERGE_SEATS_MSG = "合排方案必须含座位（merge_key 非空时 seated_count>0）"
_PAIR_COUNT_MSG = "同一合排批次至多覆盖两间考室"
_SOLO_MSG = "该考室已合排，禁止写入单室方案"
_MEMBER_PLAN_MSG = "考室留下合排指针却没有座位（本室缺少最新合排方案）"
_MASTER_PLAN_MSG = "合排主室缺少对账座位方案"
_KEY_MISMATCH_MSG = "两室合排方案批次（merge_key）不一致"
_REPOINTER_MSG = "考室已在合排组中，禁止把统一指针改派到其他主室"

# ---------------------------------------------------------------- PostgreSQL

_PG_FUNCS = f"""
CREATE OR REPLACE FUNCTION _hs_plan_merge_check() RETURNS trigger AS $$
DECLARE n int;
BEGIN
    IF NEW.merge_key IS NOT NULL THEN
        IF NEW.seated_count <= 0 THEN
            RAISE EXCEPTION '{_MERGE_SEATS_MSG}';
        END IF;
        SELECT count(DISTINCT hall_id) INTO n
            FROM seat_plans WHERE merge_key = NEW.merge_key;
        IF n > 2 THEN
            RAISE EXCEPTION '{_PAIR_COUNT_MSG}';
        END IF;
    ELSE
        IF EXISTS (SELECT 1 FROM halls WHERE id = NEW.hall_id AND merged_into IS NOT NULL) THEN
            RAISE EXCEPTION '{_SOLO_MSG}';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _hs_latest_merge_plan(p_hall_id int) RETURNS text AS $$
DECLARE k text;
BEGIN
    SELECT merge_key INTO k FROM seat_plans
        WHERE hall_id = p_hall_id AND id = (SELECT max(id) FROM seat_plans WHERE hall_id = p_hall_id);
    RETURN k;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _hs_latest_seated(p_hall_id int) RETURNS int AS $$
DECLARE n int;
BEGIN
    SELECT seated_count INTO n FROM seat_plans
        WHERE hall_id = p_hall_id AND id = (SELECT max(id) FROM seat_plans WHERE hall_id = p_hall_id);
    RETURN COALESCE(n, 0);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION _hs_hall_pointer_check() RETURNS trigger AS $$
DECLARE member_key text; master_key text;
BEGIN
    -- 已在合排组中的考室，禁止把统一指针改派给其他主室（仅更新时适用）
    IF TG_OP = 'UPDATE' AND OLD.merged_into IS NOT NULL
       AND NEW.merged_into IS DISTINCT FROM OLD.merged_into THEN
        RAISE EXCEPTION '{_REPOINTER_MSG}';
    END IF;
    IF NEW.merged_into IS NULL THEN
        RETURN NEW;
    END IF;
    member_key := _hs_latest_merge_plan(NEW.id);
    IF member_key IS NULL OR _hs_latest_seated(NEW.id) <= 0 THEN
        RAISE EXCEPTION '{_MEMBER_PLAN_MSG}';
    END IF;
    master_key := _hs_latest_merge_plan(NEW.merged_into);
    IF master_key IS NULL OR _hs_latest_seated(NEW.merged_into) <= 0 THEN
        RAISE EXCEPTION '{_MASTER_PLAN_MSG}';
    END IF;
    IF member_key <> master_key THEN
        RAISE EXCEPTION '{_KEY_MISMATCH_MSG}';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_PG_TRIGGERS = [
    "DROP TRIGGER IF EXISTS trg_plan_merge_ins ON seat_plans",
    # AFTER ROW：统计同 merge_key 考室数时 NEW 行已可见（第三室插入时计数为 3）。
    # 用普通触发器而非 CONSTRAINT TRIGGER，避免要求超级用户权限。
    "CREATE TRIGGER trg_plan_merge_ins AFTER INSERT ON seat_plans "
    "FOR EACH ROW EXECUTE FUNCTION _hs_plan_merge_check()",
    "DROP TRIGGER IF EXISTS trg_plan_merge_upd ON seat_plans",
    "CREATE TRIGGER trg_plan_merge_upd AFTER UPDATE OF merge_key, seated_count, hall_id ON seat_plans "
    "FOR EACH ROW EXECUTE FUNCTION _hs_plan_merge_check()",
    "DROP TRIGGER IF EXISTS trg_hall_pointer_ins ON halls",
    "CREATE TRIGGER trg_hall_pointer_ins BEFORE INSERT OR UPDATE OF merged_into ON halls "
    "FOR EACH ROW EXECUTE FUNCTION _hs_hall_pointer_check()",
]

# ---------------------------------------------------------------- SQLite

_LATEST_KEY = ("(SELECT merge_key FROM seat_plans WHERE hall_id = {h} "
               "AND id = (SELECT MAX(id) FROM seat_plans WHERE hall_id = {h}))")
_LATEST_SEATED = ("(SELECT COALESCE((SELECT seated_count FROM seat_plans WHERE hall_id = {h} "
                  "AND id = (SELECT MAX(id) FROM seat_plans WHERE hall_id = {h})), 0))")

_SQLITE_TRIGGERS = [
    # 1. 合排方案必须有座位
    f"""CREATE TRIGGER IF NOT EXISTS trg_plan_seats_ins AFTER INSERT ON seat_plans
    WHEN NEW.merge_key IS NOT NULL AND NEW.seated_count <= 0
    BEGIN SELECT RAISE(ABORT, '{_MERGE_SEATS_MSG}'); END""",
    # 2. 同 merge_key 至多两室
    f"""CREATE TRIGGER IF NOT EXISTS trg_plan_pair_ins AFTER INSERT ON seat_plans
    WHEN NEW.merge_key IS NOT NULL
      AND (SELECT COUNT(DISTINCT hall_id) FROM seat_plans WHERE merge_key = NEW.merge_key) > 2
    BEGIN SELECT RAISE(ABORT, '{_PAIR_COUNT_MSG}'); END""",
    # 4. 已合排考室禁止单室方案
    f"""CREATE TRIGGER IF NOT EXISTS trg_plan_solo_ins AFTER INSERT ON seat_plans
    WHEN NEW.merge_key IS NULL
      AND EXISTS (SELECT 1 FROM halls WHERE id = NEW.hall_id AND merged_into IS NOT NULL)
    BEGIN SELECT RAISE(ABORT, '{_SOLO_MSG}'); END""",
    # 3a. 留指针的考室：本室最新方案必须为有座位的合排方案
    f"""CREATE TRIGGER IF NOT EXISTS trg_hall_member_ins BEFORE INSERT ON halls
    WHEN NEW.merged_into IS NOT NULL
      AND ({_LATEST_KEY.format(h="NEW.id")} IS NULL
           OR {_LATEST_SEATED.format(h="NEW.id")} <= 0)
    BEGIN SELECT RAISE(ABORT, '{_MEMBER_PLAN_MSG}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS trg_hall_member_upd BEFORE UPDATE OF merged_into ON halls
    WHEN NEW.merged_into IS NOT NULL
      AND ({_LATEST_KEY.format(h="NEW.id")} IS NULL
           OR {_LATEST_SEATED.format(h="NEW.id")} <= 0)
    BEGIN SELECT RAISE(ABORT, '{_MEMBER_PLAN_MSG}'); END""",
    # 3b. 主室最新方案必须为有座位的合排方案
    f"""CREATE TRIGGER IF NOT EXISTS trg_hall_master_ins BEFORE INSERT ON halls
    WHEN NEW.merged_into IS NOT NULL
      AND ({_LATEST_KEY.format(h="NEW.merged_into")} IS NULL
           OR {_LATEST_SEATED.format(h="NEW.merged_into")} <= 0)
    BEGIN SELECT RAISE(ABORT, '{_MASTER_PLAN_MSG}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS trg_hall_master_upd BEFORE UPDATE OF merged_into ON halls
    WHEN NEW.merged_into IS NOT NULL
      AND ({_LATEST_KEY.format(h="NEW.merged_into")} IS NULL
           OR {_LATEST_SEATED.format(h="NEW.merged_into")} <= 0)
    BEGIN SELECT RAISE(ABORT, '{_MASTER_PLAN_MSG}'); END""",
    # 3c. 两室最新方案 merge_key 必须一致
    f"""CREATE TRIGGER IF NOT EXISTS trg_hall_key_ins BEFORE INSERT ON halls
    WHEN NEW.merged_into IS NOT NULL
      AND {_LATEST_KEY.format(h="NEW.id")} <> {_LATEST_KEY.format(h="NEW.merged_into")}
    BEGIN SELECT RAISE(ABORT, '{_KEY_MISMATCH_MSG}'); END""",
    f"""CREATE TRIGGER IF NOT EXISTS trg_hall_key_upd BEFORE UPDATE OF merged_into ON halls
    WHEN NEW.merged_into IS NOT NULL
      AND {_LATEST_KEY.format(h="NEW.id")} <> {_LATEST_KEY.format(h="NEW.merged_into")}
    BEGIN SELECT RAISE(ABORT, '{_KEY_MISMATCH_MSG}'); END""",
    # 已合排考室禁止把统一指针改派到其他主室
    f"""CREATE TRIGGER IF NOT EXISTS trg_hall_repointer_upd BEFORE UPDATE OF merged_into ON halls
    WHEN OLD.merged_into IS NOT NULL AND NEW.merged_into IS NOT OLD.merged_into
    BEGIN SELECT RAISE(ABORT, '{_REPOINTER_MSG}'); END""",
]


def _install(connection) -> None:
    dialect = connection.engine.dialect.name
    if dialect == "postgresql":
        connection.execute(text(_PG_FUNCS))
        for ddl in _PG_TRIGGERS:
            connection.execute(text(ddl))
    elif dialect == "sqlite":
        for ddl in _SQLITE_TRIGGERS:
            connection.execute(text(ddl))


def _on_metadata_create(_metadata, connection, **_kw) -> None:
    # MetaData.after_create 在所有表创建完毕后触发一次，不依赖本模块的导入时机
    _install(connection)


event.listen(Base.metadata, "after_create", _on_metadata_create)
