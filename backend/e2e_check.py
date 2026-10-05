"""端到端验收演练：真实 FastAPI 应用 + 真实种子，覆盖成功对账 / 失败双室回滚 / 第三室隔离。"""
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Candidate, Hall, SeatPlan
from app.services.seed import seed_if_empty

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(bind=engine)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()
seed_if_empty(db)
db.close()

# 额外构造一间“必失败”考室 H104：1x2、min_dist=2、2 名考生（容量够但间距排不下）
db = SessionLocal()
bad = Hall(code="H104", name="四号考室", rows=1, cols=2, min_manhattan=2)
db.add(bad); db.flush()
p1 = db.scalars(select(Candidate).limit(1)).first()
paper = p1.paper_id
n0 = db.scalar(select(func.count()).select_from(Candidate))
for i in range(2):
    db.add(Candidate(hall_id=bad.id, name=f"坏室生{i}", ticket_no=f"BAD{i}", paper_id=paper))
db.commit()
halls = {h.code: h.id for h in db.scalars(select(Hall)).all()}
db.close()
H1, H2, H3, H4 = halls["H101"], halls["H102"], halls["H103"], halls["H104"]


def _get_db():
    d = SessionLocal()
    try:
        yield d
    finally:
        d.close()


app.dependency_overrides[get_db] = _get_db
c = TestClient(app)

print("== 0. 初始三/四室，均为独立 ==")
hs = c.get("/api/halls").json()
assert all(h["merged_into"] is None for h in hs), hs
print("   halls:", [(h["code"], h["id"]) for h in hs])

print("== 1. 第三室先排座，留存基线方案 ==")
s3_before = c.post(f"/api/seating/run?hall_id={H3}").json()
db = SessionLocal()
p3_before = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == H3).order_by(SeatPlan.id.desc())).first()
third_count_before = db.scalar(select(func.count()).select_from(SeatPlan).where(SeatPlan.hall_id == H3))
db.close()
print("   H3 基线:", s3_before["stats"])

print("== 2. 申请 H1+H2 合排（成功路径）==")
r = c.post("/api/seating/merge", json={"hall_a_id": H1, "hall_b_id": H2})
assert r.status_code == 200, r.text
m = r.json()
print("   合排已座:", m["stats"]["seated"], "未排:", m["stats"]["unplaced"], "批次:", m["merge_key"])
assert m["stats"]["seated"] == 20 and m["stats"]["unplaced"] == 0

db = SessionLocal()
ha, hb = db.get(Hall, H1), db.get(Hall, H2)
assert ha.merged_into == hb.merged_into == min(H1, H2)
pa = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == H1).order_by(SeatPlan.id.desc())).first()
pb = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == H2).order_by(SeatPlan.id.desc())).first()
assert pa.merge_key == pb.merge_key == m["merge_key"]
assert pa.seated_count == 12 and pb.seated_count == 8
h3 = db.get(Hall, H3)
assert h3.merged_into is None
p3_after = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == H3).order_by(SeatPlan.id.desc())).first()
assert p3_after.id == p3_before.id
third_count_after = db.scalar(select(func.count()).select_from(SeatPlan).where(SeatPlan.hall_id == H3))
assert third_count_after == third_count_before
db.close()
print("   ✓ 两室统一指针 + 各自对账座位方案（12/8），第三室零改动")

print("== 3. 合排后再分室查看：人数加总=合排已座 ==")
st1 = c.get(f"/api/seating/stats?hall_id={H1}").json()
st2 = c.get(f"/api/seating/stats?hall_id={H2}").json()
print("   H1 本室 seated:", st1["seated"], " H2 本室 seated:", st2["seated"],
      " 合排已座:", st1["merged_seated"])
assert st1["seated"] + st2["seated"] == st1["merged_seated"] == st2["merged_seated"] == 20
l1, l2 = c.get(f"/api/seating/latest?hall_id={H1}").json(), c.get(f"/api/seating/latest?hall_id={H2}").json()
ids = {a["candidate_id"] for a in l1["assignments"]} | {a["candidate_id"] for a in l2["assignments"]}
assert len(ids) == 20
assert l1["merge_key"] == l2["merge_key"]
print("   ✓ 分室 12+8=20，两室考生不丢不重，批次一致")

print("== 4. 已合排考室禁止单室重排 ==")
assert c.post(f"/api/seating/run?hall_id={H1}").status_code == 409
print("   ✓ /run 返回 409")

print("== 5. 用 H4（间距必失败）与未参与的 H3 申请合排（失败路径）==")
r = c.post("/api/seating/merge", json={"hall_a_id": H3, "hall_b_id": H4})
assert r.status_code == 409, (r.status_code, r.text)
print("   服务端拒绝:", json.loads(r.text)["detail"][:60], "...")

db = SessionLocal()
assert db.get(Hall, H3).merged_into is None
assert db.get(Hall, H4).merged_into is None
stray = db.scalars(select(SeatPlan).where(SeatPlan.merge_key.is_not(None))).all()
keys = {p.merge_key for p in stray}
assert keys == {m["merge_key"]}, "失败后出现了新的残留合排批次"
p3_now = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == H3).order_by(SeatPlan.id.desc())).first()
assert p3_now.id == p3_before.id
data3 = json.loads(p3_now.result_json)
assert data3["stats"] == s3_before["stats"]
h4_plans = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == H4)).all()
assert h4_plans == [], "失败合排给从未排座的 H4 留下了方案"
db.close()
print("   ✓ 双室回滚：H3 方案/统计复原，H4 无方案，无残留指针/新批次")

s3_now = c.get(f"/api/seating/stats?hall_id={H3}").json()
assert s3_now["seated"] == s3_before["stats"]["seated"] and s3_now.get("merged") is None
print("   ✓ H3 统计页仍为独立考室且人数 =", s3_now["seated"])

print("== 6. 已有合排组的成员不能再与他人合排，且失败不破坏原合排 ==")
r = c.post("/api/seating/merge", json={"hall_a_id": H1, "hall_b_id": H3})
assert r.status_code == 409
db = SessionLocal()
assert db.get(Hall, H1).merged_into == min(H1, H2)
assert db.get(Hall, H3).merged_into is None
db.close()
print("   ✓ 拒绝且原 H1⇄H2 合排指针、H3 独立状态不变")

print("\n全部端到端验收通过 ✅")
