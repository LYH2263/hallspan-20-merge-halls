import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Candidate, Hall, SeatPlan
from app.services.merge_service import merge_halls
from app.services.seat_engine import MergeError, find_violations, place_candidates, plan_to_dict

router = APIRouter(prefix="/seating", tags=["seating"])


class MergeRequest(BaseModel):
    hall_a_id: int
    hall_b_id: int


def _run_single(db: Session, hall: Hall) -> dict:
    cands = [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
             for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall.id)).all()]
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    plan = SeatPlan(hall_id=hall.id, created_at=datetime.utcnow(),
                    result_json=json.dumps(result, ensure_ascii=False),
                    merge_key=None, seated_count=result["stats"]["seated"])
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, **result}


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    if hall.merged_into is not None:
        raise HTTPException(409, "该考室已合排，不能单室重排；合排为两室共享方案")
    return _run_single(db, hall)


def _latest_plan(db: Session, hall_id: int) -> SeatPlan | None:
    return db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()


def _merged_view(db: Session, hall: Hall) -> dict:
    """跟随统一指针读取合排方案：返回本室切片 + 双室对账 + 合排合计。"""
    master_id = hall.merged_into
    members = db.scalars(select(Hall).where(Hall.merged_into == master_id)).all()
    if len(members) != 2:
        raise HTTPException(500, "合排指针损坏：合排组必须恰好两间考室")
    members.sort(key=lambda h: h.id)

    plans = {h.id: _latest_plan(db, h.id) for h in members}
    if any(p is None for p in plans.values()):
        # 触发器本应阻止该状态：留下合排指针却没有座位
        raise HTTPException(500, "合排对账损坏：存在合排指针但缺少座位方案")

    keys = {p.merge_key for p in plans.values()}
    if len(keys) != 1 or None in keys or any(p.seated_count <= 0 for p in plans.values()):
        raise HTTPException(500, "合排对账损坏：批次指针缺失/不一致或存在空座位方案")
    merge_key = next(iter(keys))

    datas = {hid: json.loads(p.result_json) for hid, p in plans.items()}
    own_plan = plans[hall.id]
    own = datas[hall.id]
    partner_id = next(h.id for h in members if h.id != hall.id)

    # 分室对账：以冗余 seated_count 为准重算合计，并与方案内统计互相校验
    room_stats = []
    for h in members:
        st = datas[h.id]["stats"]
        if st["seated"] != plans[h.id].seated_count:
            raise HTTPException(500, f"考室 {h.id} 统计与座位数不一致")
        room_stats.append({"hall_id": h.id, "name": h.name, **st})
    merged_seated = sum(r["seated"] for r in room_stats)
    stored_total = datas[master_id].get("merge_stats", {}).get("seated")
    if stored_total is not None and stored_total != merged_seated:
        raise HTTPException(500, "合排对账损坏：分室人数加总不等于合排已座")

    merged_stats = {
        "seated": merged_seated,
        "unplaced": sum(r["unplaced"] for r in room_stats),
        "violations": sum(r["violations"] for r in room_stats),
        "capacity": sum(r["capacity"] for r in room_stats),
    }

    return {
        "id": own_plan.id,
        "rows": own["rows"],
        "cols": own["cols"],
        "assignments": own["assignments"],
        "unplaced": own["unplaced"],
        "violations": own["violations"],
        "stats": own["stats"],
        "hall": {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan},
        "merged": True,
        "merge_key": merge_key,
        "master_id": master_id,
        "partner_id": partner_id,
        "room_stats": room_stats,
        "merged_stats": merged_stats,
    }


@router.post("/merge")
def merge_two_halls(body: MergeRequest, db: Session = Depends(get_db)):
    """两考室申请一次合排。成功两室都留下对账方案与统一指针；任一步失败双室整体回滚。"""
    try:
        result = merge_halls(db, body.hall_a_id, body.hall_b_id)
    except MergeError as exc:
        raise HTTPException(409, str(exc))
    return result


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    if hall.merged_into is not None:
        return _merged_view(db, hall)
    plan = _latest_plan(db, hall_id)
    if not plan:
        return _run_single(db, hall)
    data = json.loads(plan.result_json)
    return {"id": plan.id, **data}


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "violations": data.get("violations", []),
            "unplaced": data.get("unplaced", [])}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    out = {"hall_id": hall_id, **data.get("stats", {})}
    if data.get("merged"):
        # 分室查看：本室人数 + 同组另一室人数，两者加总必须等于合排已座
        out.update({
            "merged": True,
            "merge_key": data["merge_key"],
            "master_id": data["master_id"],
            "partner_id": data["partner_id"],
            "room_stats": data["room_stats"],
            "merged_seated": data["merged_stats"]["seated"],
        })
        assert sum(r["seated"] for r in data["room_stats"]) == data["merged_stats"]["seated"]
    return out
