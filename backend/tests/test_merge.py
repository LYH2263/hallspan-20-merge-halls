"""合排（两考室合并排座）事务语义测试。

覆盖：成功时双室各留可对账方案且人数加总等于合排已座；任一步失败双室整体回滚、
无残留合排指针；未参与的第三室不被改动；种子合排失败回滚、成功时对账平衡。
"""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.router import api_router
from app.database import Base, get_db
from app.models.models import Candidate, Hall, PaperSet, SeatPlan
from app.services import merge as merge_mod
from app.services.merge import MergeError, run_merge
from app.services.seed import seed_if_empty


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db):
    app = FastAPI()
    app.include_router(api_router, prefix="/api")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _papers(db):
    ids = []
    for code, title in [("P-A", "A 卷"), ("P-B", "B 卷"), ("P-C", "C 卷")]:
        p = PaperSet(code=code, title=title)
        db.add(p)
        db.flush()
        ids.append(p.id)
    return ids


def _hall(db, code, rows, cols, mm=2):
    h = Hall(code=code, name=f"考室{code}", rows=rows, cols=cols, min_manhattan=mm)
    db.add(h)
    db.flush()
    return h


def _candidates(db, hall_id, n, paper_ids, base):
    out = []
    for i in range(n):
        c = Candidate(hall_id=hall_id, name=f"C{base+i}", ticket_no=f"T{base+i}",
                      paper_id=paper_ids[i % len(paper_ids)])
        db.add(c)
        out.append(c)
    db.flush()
    return out


def _plans(db, hall_id):
    return db.scalars(select(SeatPlan).where(SeatPlan.hall_id == hall_id)
                      .order_by(SeatPlan.id)).all()


def _three_halls(db):
    paper_ids = _papers(db)
    h1 = _hall(db, "A", 5, 6)
    h2 = _hall(db, "B", 4, 6)
    h3 = _hall(db, "C", 4, 5)
    c1 = _candidates(db, h1.id, 12, paper_ids, 100)
    c2 = _candidates(db, h2.id, 10, paper_ids, 200)
    _candidates(db, h3.id, 8, paper_ids, 300)
    db.commit()
    return h1, h2, h3, c1, c2


def test_merge_success_two_plans_one_pointer_balanced(db):
    h1, h2, h3, c1, c2 = _three_halls(db)
    res = run_merge(db, h1.id, h2.id)

    plans1, plans2, plans3 = _plans(db, h1.id), _plans(db, h2.id), _plans(db, h3.id)
    # 两室都留下方案，且共用同一合排指针；第三室未被改动
    assert len(plans1) == 1 and len(plans2) == 1
    assert plans1[0].merge_id == plans2[0].merge_id == res["merge_id"]
    assert plans3 == []

    d1 = json.loads(plans1[0].result_json)
    d2 = json.loads(plans2[0].result_json)
    # 分室查看：人数加总 == 合排已座（两条方案均可对账）
    seated_sum = d1["stats"]["seated"] + d2["stats"]["seated"]
    assert seated_sum == res["merged"]["seated"]
    assert d1["merge"]["merged_seated"] == d2["merge"]["merged_seated"] == seated_sum
    assert d1["merge"]["partner_hall_id"] == h2.id
    assert d2["merge"]["partner_hall_id"] == h1.id

    # 考生不丢：每室 已座+未排 == 本室考生；跨室无重复
    ids1 = [a["candidate_id"] for a in d1["assignments"]] + [c["id"] for c in d1["unplaced"]]
    ids2 = [a["candidate_id"] for a in d2["assignments"]] + [c["id"] for c in d2["unplaced"]]
    assert sorted(ids1) == sorted(c.id for c in c1)
    assert sorted(ids2) == sorted(c.id for c in c2)
    assert not set(ids1) & set(ids2)

    # 座位落在本室网格内
    assert all(0 <= a["row"] < h1.rows and 0 <= a["col"] < h1.cols for a in d1["assignments"])
    assert all(0 <= a["row"] < h2.rows and 0 <= a["col"] < h2.cols for a in d2["assignments"])


def test_merge_same_hall_rejected(db):
    h1, _, _, _, _ = _three_halls(db)
    with pytest.raises(MergeError):
        run_merge(db, h1.id, h1.id)
    assert _plans(db, h1.id) == []


def test_merge_missing_hall_rejected(db):
    h1, h2, _, _, _ = _three_halls(db)
    with pytest.raises(MergeError) as e:
        run_merge(db, h1.id, 999)
    assert e.value.status_code == 404
    assert _plans(db, h1.id) == [] and _plans(db, h2.id) == []


def test_merge_empty_hall_rejected(db):
    h1, h2, _, _, _ = _three_halls(db)
    empty = _hall(db, "EMPTY", 3, 3)
    db.commit()
    with pytest.raises(MergeError):
        run_merge(db, h1.id, empty.id)
    assert _plans(db, h1.id) == [] and _plans(db, empty.id) == []
    assert _plans(db, h2.id) == []


def test_merge_engine_failure_rolls_back_both(db, monkeypatch):
    h1, h2, _, _, _ = _three_halls(db)
    pre1 = SeatPlan(hall_id=h1.id, result_json='{"stats": {"seated": 1}}')
    pre2 = SeatPlan(hall_id=h2.id, result_json='{"stats": {"seated": 2}}')
    db.add_all([pre1, pre2])
    db.commit()

    def boom(*a, **k):
        raise ValueError("forced engine failure")

    monkeypatch.setattr(merge_mod, "merge_plan", boom)
    with pytest.raises(MergeError):
        run_merge(db, h1.id, h2.id)
    # 双室退回合排前：合排前方案仍在且最新，全库无合排指针
    assert [p.id for p in _plans(db, h1.id)] == [pre1.id]
    assert [p.id for p in _plans(db, h2.id)] == [pre2.id]
    assert db.scalar(select(func.count()).select_from(SeatPlan).where(SeatPlan.merge_id.isnot(None))) == 0


def test_merge_commit_failure_rolls_back_both(db, monkeypatch):
    h1, h2, _, _, _ = _three_halls(db)

    def bad_commit():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "commit", bad_commit)
    with pytest.raises(RuntimeError):
        run_merge(db, h1.id, h2.id)
    db.rollback()
    # 禁止一室成功一室空：两室都无新方案，无残留合排指针
    assert _plans(db, h1.id) == [] and _plans(db, h2.id) == []
    assert db.scalar(select(func.count()).select_from(SeatPlan).where(SeatPlan.merge_id.isnot(None))) == 0


def test_seed_merge_success_balanced(db):
    seed_if_empty(db)
    halls = db.scalars(select(Hall).order_by(Hall.id)).all()
    assert len(halls) == 3
    p1 = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == halls[0].id)
                    .order_by(SeatPlan.id.desc())).first()
    p2 = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == halls[1].id)
                    .order_by(SeatPlan.id.desc())).first()
    assert p1 is not None and p2 is not None
    assert p1.merge_id and p1.merge_id == p2.merge_id
    d1, d2 = json.loads(p1.result_json), json.loads(p2.result_json)
    # 两室页人数相加 == 合排已座
    assert d1["stats"]["seated"] + d2["stats"]["seated"] == d1["merge"]["merged_seated"]
    assert d2["merge"]["merged_seated"] == d1["merge"]["merged_seated"]
    # 第三室不参与：无任何方案
    assert _plans(db, halls[2].id) == []


def test_seed_merge_failure_rolls_back_clean(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("forced seed merge failure")

    monkeypatch.setattr("app.services.seed.run_merge", boom)
    seed_if_empty(db)  # 不抛出
    # 基础数据保留，双室回滚：无任何方案、无残留合排指针
    assert db.scalar(select(func.count()).select_from(Hall)) == 3
    assert db.scalar(select(func.count()).select_from(Candidate)) == 30
    assert db.scalar(select(func.count()).select_from(SeatPlan)) == 0
    assert db.scalar(select(func.count()).select_from(SeatPlan).where(SeatPlan.merge_id.isnot(None))) == 0


def test_api_merge_success_and_reconcile(client, db):
    h1, h2, _, _, _ = _three_halls(db)
    res = client.post(f"/api/seating/merge?hall_a={h1.id}&hall_b={h2.id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["merged"]["seated"] == sum(h["stats"]["seated"] for h in body["halls"])

    rec = client.get(f"/api/seating/merge/{body['merge_id']}")
    assert rec.status_code == 200
    rbody = rec.json()
    assert rbody["balanced"] is True
    assert rbody["seated_sum"] == rbody["merged_seated"]
    assert len(rbody["halls"]) == 2

    # 分室查看：两室页人数加总 == 合排已座
    s1 = client.get(f"/api/seating/stats?hall_id={h1.id}").json()
    s2 = client.get(f"/api/seating/stats?hall_id={h2.id}").json()
    assert s1["seated"] + s2["seated"] == body["merged"]["seated"]


def test_api_merge_failure_writes_nothing(client, db):
    h1, h2, h3, _, _ = _three_halls(db)
    res = client.post(f"/api/seating/merge?hall_a={h1.id}&hall_b=999")
    assert res.status_code == 404
    assert db.scalar(select(func.count()).select_from(SeatPlan)) == 0
    # 第三室未被改动
    assert _plans(db, h3.id) == []
    assert db.scalar(select(func.count()).select_from(Candidate)
                     .where(Candidate.hall_id == h3.id)) == 8


def test_api_merge_unknown_id_404(client, db):
    _three_halls(db)
    res = client.get("/api/seating/merge/nonexistent")
    assert res.status_code == 404
