"""两考室合排编排：算法调用 + 单事务双写 + 统一指针。

任何一步失败都由数据库事务整体回滚 —— 两室新方案、统计、未排、合排指针要么全部生效，
要么全部不存在。第三室不在本服务的任何读写路径上。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, SeatPlan
from app.services.seat_engine import MergeError, RoomInput, place_merged


def load_room(db: Session, hall: Hall) -> RoomInput:
    cands = [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
        for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall.id)).all()
    ]
    return RoomInput(hall.id, hall.rows, hall.cols, hall.min_manhattan, cands)


def _room_summary(slice_payload: dict) -> dict:
    return {"hall_id": slice_payload["hall_id"], **slice_payload["stats"]}


def merge_halls(db: Session, hall_a_id: int, hall_b_id: int) -> dict:
    if hall_a_id == hall_b_id:
        raise MergeError("合排必须选择两间不同的考室")

    # 对两室行按 id 加行锁（PG 生效；SQLite 忽略）：串行化涉及相同考室的并发合排，
    # 避免两个事务互相覆盖统一指针；固定加锁顺序以防死锁。
    locked = {h.id: h for h in db.scalars(
        select(Hall).where(Hall.id.in_([hall_a_id, hall_b_id])).order_by(Hall.id).with_for_update()
    ).all()}
    hall_a, hall_b = locked.get(hall_a_id), locked.get(hall_b_id)
    if not hall_a or not hall_b:
        raise MergeError("考室不存在")
    if hall_a.merged_into is not None or hall_b.merged_into is not None:
        raise MergeError("考室已处于合排状态，不能再次合排")

    room_a = load_room(db, hall_a)
    room_b = load_room(db, hall_b)
    if not room_a.candidates or not room_b.candidates:
        raise MergeError("参与合排的考室必须各有考生（合排方案不得没有座位）")

    # 1) 先纯内存计算；失败在此抛出，数据库尚无任何写入
    payload = place_merged(room_a, room_b)

    merge_key = f"MG-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}"
    master_id = min(hall_a_id, hall_b_id)
    room_summaries = [_room_summary(s) for s in payload["room_slices"]]

    # 2) 双室方案 + 统一指针在同一事务内提交；任一步失败整体回滚
    try:
        # 先写两室对账方案（含座位），再立统一指针 —— 顺序满足触发器前置条件
        for sl, partner_id in ((payload["room_slices"][0], hall_b_id),
                               (payload["room_slices"][1], hall_a_id)):
            snapshot = dict(sl)
            snapshot["merge"] = True
            snapshot["merge_key"] = merge_key
            snapshot["merge_master"] = master_id
            snapshot["merge_partner"] = partner_id
            snapshot["merge_stats"] = payload["stats"]
            snapshot["room_stats"] = room_summaries
            db.add(SeatPlan(
                hall_id=sl["hall_id"],
                created_at=datetime.utcnow(),
                result_json=json.dumps(snapshot, ensure_ascii=False),
                merge_key=merge_key,
                seated_count=sl["stats"]["seated"],
            ))
        db.flush()  # 方案级触发器在此校验：有座位、至多两室

        hall_a.merged_into = master_id
        hall_b.merged_into = master_id
        db.flush()  # 指针级触发器在此校验：双室均有同批次合排座位方案，禁止单边指针

        db.commit()
    except MergeError:
        db.rollback()
        raise
    except Exception as exc:  # 触发器拦截 / 任何中途失败：双室全部回滚
        db.rollback()
        raise MergeError(f"合排提交失败，双室已回滚至合排前：{exc.__class__.__name__}") from exc

    return {"merge_key": merge_key, "master_id": master_id, **payload}
