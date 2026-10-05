import json

import pytest
from sqlalchemy import select

from app.models.models import Hall, SeatPlan


def _plan_count(db, hall_id):
    return len(db.scalars(select(SeatPlan).where(SeatPlan.hall_id == hall_id)).all())


def _latest_row(db, hall_id):
    return db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()


# --------------------------------------------------------------- 成功：双室对账

def test_merge_success_both_halls_get_reconcilable_plans(client, seeded, SessionTest):
    h1, h2, h3, _h4, _h5 = seeded

    resp = client.post("/api/seating/merge", json={"hall_a_id": h1, "hall_b_id": h2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    merge_key = body["merge_key"]
    assert body["stats"]["seated"] == 20
    assert body["stats"]["unplaced"] == 0

    db = SessionTest()
    try:
        ha, hb = db.get(Hall, h1), db.get(Hall, h2)
        # 统一指针：两室都指向同一主室
        assert ha.merged_into == hb.merged_into == min(h1, h2)
        pa, pb = _latest_row(db, h1), _latest_row(db, h2)
        # 两室都留下同批次合排方案且各自有座位
        assert pa.merge_key == pb.merge_key == merge_key
        assert pa.seated_count == 12 and pb.seated_count == 8
        assert pa.seated_count > 0 and pb.seated_count > 0
    finally:
        db.close()

    # 分室再查看：两室页人数相加等于合排已座
    s1 = client.get(f"/api/seating/stats?hall_id={h1}").json()
    s2 = client.get(f"/api/seating/stats?hall_id={h2}").json()
    assert s1["merged"] is True and s2["merged"] is True
    assert s1["seated"] + s2["seated"] == s1["merged_seated"] == 20
    assert {r["hall_id"] for r in s1["room_stats"]} == {h1, h2}
    assert sum(r["seated"] for r in s1["room_stats"]) == s1["merged_seated"]

    # 考生不丢：两室切片中的考生并集仍是全部 20 人
    l1 = client.get(f"/api/seating/latest?hall_id={h1}").json()
    l2 = client.get(f"/api/seating/latest?hall_id={h2}").json()
    ids1 = {a["candidate_id"] for a in l1["assignments"]}
    ids2 = {a["candidate_id"] for a in l2["assignments"]}
    assert len(ids1) == 12 and len(ids2) == 8
    assert ids1.isdisjoint(ids2)
    assert l1["merge_key"] == l2["merge_key"] == merge_key


def test_merged_hall_rejects_single_run(client, seeded):
    h1, h2, _h3, _h4, _h5 = seeded
    assert client.post("/api/seating/merge", json={"hall_a_id": h1, "hall_b_id": h2}).status_code == 200
    assert client.post(f"/api/seating/run?hall_id={h1}").status_code == 409
    assert client.post(f"/api/seating/run?hall_id={h2}").status_code == 409


# --------------------------------------------------------------- 失败：双室回滚

def test_merge_failure_rolls_both_halls_back(client, seeded, SessionTest):
    h1, h2, h3, h4, _h5 = seeded  # h4 = 1x1 容量，2 名考生

    # 合排前先各跑一次单室排座，留存旧方案/统计/未排
    old1 = client.post(f"/api/seating/run?hall_id={h1}").json()
    old4 = client.post(f"/api/seating/run?hall_id={h4}").json()
    assert old4["stats"]["seated"] == 1 and old4["stats"]["unplaced"] == 1

    db = SessionTest()
    before_p1 = _latest_row(db, h1)
    before_p4 = _latest_row(db, h4)
    before_counts = {h: _plan_count(db, h) for h in (h1, h4)}
    db.close()

    # 合排必失败（容量不足）
    resp = client.post("/api/seating/merge", json={"hall_a_id": h1, "hall_b_id": h4})
    assert resp.status_code == 409

    db = SessionTest()
    try:
        # 无残留合排指针
        assert db.get(Hall, h1).merged_into is None
        assert db.get(Hall, h4).merged_into is None
        # 无残留合排方案
        stray = db.scalars(select(SeatPlan).where(SeatPlan.merge_key.is_not(None))).all()
        assert stray == []
        # 方案行数未增加，最新方案仍是合排前那份
        assert {h: _plan_count(db, h) for h in (h1, h4)} == before_counts
        assert _latest_row(db, h1).id == before_p1.id
        assert _latest_row(db, h4).id == before_p4.id
    finally:
        db.close()

    # 两室统计/未排全部退回合排前
    now1 = client.get(f"/api/seating/latest?hall_id={h1}").json()
    now4 = client.get(f"/api/seating/latest?hall_id={h4}").json()
    assert now1["stats"] == old1["stats"]
    assert now4["stats"] == old4["stats"]
    assert len(now4["unplaced"]) == 1


def test_merge_failure_does_not_leave_pointer_without_seats(client, seeded, SessionTest):
    h1, _h2, _h3, h4, _h5 = seeded
    client.post("/api/seating/merge", json={"hall_a_id": h1, "hall_b_id": h4})
    db = SessionTest()
    try:
        assert db.scalars(select(SeatPlan).where(SeatPlan.merge_key.is_not(None))).all() == []
        assert db.get(Hall, h1).merged_into is None
        assert db.get(Hall, h4).merged_into is None
    finally:
        db.close()


# --------------------------------------------------------------- 第三室隔离

def test_third_hall_untouched_on_success_and_failure(client, seeded, SessionTest):
    h1, h2, h3, h4, _h5 = seeded

    old3 = client.post(f"/api/seating/run?hall_id={h3}").json()
    db = SessionTest()
    third_before = _latest_row(db, h3)
    third_plans_before = _plan_count(db, h3)
    db.close()

    # 成功合排不碰第三室
    assert client.post("/api/seating/merge", json={"hall_a_id": h1, "hall_b_id": h2}).status_code == 200
    db = SessionTest()
    try:
        assert db.get(Hall, h3).merged_into is None
        assert _plan_count(db, h3) == third_plans_before
        assert _latest_row(db, h3).id == third_before.id
    finally:
        db.close()
    assert client.get(f"/api/seating/stats?hall_id={h3}").json()["seated"] == old3["stats"]["seated"]

    # 失败合排也不碰第三室
    assert client.post("/api/seating/merge", json={"hall_a_id": h3, "hall_b_id": h4}).status_code == 409
    db = SessionTest()
    try:
        assert db.get(Hall, h3).merged_into is None
        assert _plan_count(db, h3) == third_plans_before
        assert _latest_row(db, h3).id == third_before.id
        data = json.loads(_latest_row(db, h3).result_json)
        assert data["stats"] == old3["stats"]
    finally:
        db.close()


# --------------------------------------------------------------- 数据库触发器防线

def test_db_rejects_pointer_without_plan(seeded, SessionTest):
    h1, h2, _h3, _h4, _h5 = seeded
    db = SessionTest()
    try:
        # 直接绕过服务层立指针：两室均无合排座位方案，触发器必须拒绝
        db.get(Hall, h1).merged_into = h1
        with pytest.raises(Exception):
            db.flush()
        db.rollback()
        assert db.get(Hall, h1).merged_into is None
    finally:
        db.close()


def test_db_rejects_single_sided_pointer(seeded, SessionTest):
    """h2 立指针指向 h1，但主室 h1 没有任何合排座位方案：触发器拒绝单边指针。"""
    h1, h2, _h3, _h4, _h5 = seeded
    db = SessionTest()
    try:
        db.get(Hall, h2).merged_into = h1
        with pytest.raises(Exception):
            db.flush()
        db.rollback()
        assert db.get(Hall, h2).merged_into is None
        assert db.get(Hall, h1).merged_into is None
    finally:
        db.close()


def test_db_rejects_merge_plan_with_zero_seats(seeded, SessionTest):
    from datetime import datetime
    h1, _h2, _h3, _h4, _h5 = seeded
    db = SessionTest()
    try:
        db.add(SeatPlan(hall_id=h1, created_at=datetime.utcnow(),
                        result_json="{}", merge_key="MG-ZERO", seated_count=0))
        with pytest.raises(Exception):
            db.flush()
        db.rollback()
    finally:
        db.close()


def test_merge_same_hall_rejected(client, seeded):
    h1, *_ = seeded
    assert client.post("/api/seating/merge", json={"hall_a_id": h1, "hall_b_id": h1}).status_code == 409


def test_db_rejects_repointer_after_merge(client, seeded, SessionTest):
    """成功合排后，直接改派统一指针到第三室必须被触发器拒绝，且原指针不变。"""
    h1, h2, h3, _h4, _h5 = seeded
    assert client.post("/api/seating/merge", json={"hall_a_id": h1, "hall_b_id": h2}).status_code == 200
    db = SessionTest()
    try:
        db.get(Hall, h1).merged_into = h3
        with pytest.raises(Exception):
            db.flush()
        db.rollback()
        assert db.get(Hall, h1).merged_into == min(h1, h2)
        assert db.get(Hall, h3).merged_into is None
    finally:
        db.close()


def test_merge_failure_by_distance_constraint_rolls_both_back(client, seeded, SessionTest):
    """容量足够但间距约束导致无法落座（区别于容量预检）：仍须双室回滚、无残留指针。"""
    h1, _h2, _h3, _h4, h5 = seeded  # h5 = 1x2、min_dist=2、2 名考生：物理上排不下

    before = client.post(f"/api/seating/run?hall_id={h1}").json()
    db = SessionTest()
    before_count = _plan_count(db, h1)
    before_id = _latest_row(db, h1).id
    db.close()

    resp = client.post("/api/seating/merge", json={"hall_a_id": h1, "hall_b_id": h5})
    assert resp.status_code == 409

    db = SessionTest()
    try:
        assert db.get(Hall, h1).merged_into is None
        assert db.get(Hall, h5).merged_into is None
        assert db.scalars(select(SeatPlan).where(SeatPlan.merge_key.is_not(None))).all() == []
        assert _plan_count(db, h1) == before_count
        assert _latest_row(db, h1).id == before_id
    finally:
        db.close()
    assert client.get(f"/api/seating/latest?hall_id={h1}").json()["stats"] == before["stats"]
