import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate, Hall, SeatPlan
from app.services.merge import MergeError, run_merge
from app.services.seat_engine import find_violations, place_candidates, plan_to_dict
router = APIRouter(prefix="/seating", tags=["seating"])

@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall: raise HTTPException(404, "考室不存在")
    cands = [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
             for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id)).all()]
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    plan = SeatPlan(hall_id=hall_id, created_at=datetime.utcnow(), result_json=json.dumps(result, ensure_ascii=False))
    db.add(plan); db.commit(); db.refresh(plan)
    return {"id": plan.id, **result}

@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    plan = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())).first()
    if not plan:
        return run_seating(hall_id=hall_id, db=db)
    data = json.loads(plan.result_json)
    return {"id": plan.id, **data}

@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "violations": data.get("violations", []), "unplaced": data.get("unplaced", [])}

@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, **data.get("stats", {})}

@router.post("/merge")
def merge(hall_a: int, hall_b: int, db: Session = Depends(get_db)):
    """两考室申请一次合排：成功则双室各留可对账方案，任一步失败则双室整体回滚。"""
    try:
        return run_merge(db, hall_a, hall_b)
    except MergeError as e:
        raise HTTPException(e.status_code, str(e))

@router.get("/merge/{merge_id}")
def merge_detail(merge_id: str, db: Session = Depends(get_db)):
    """合排对账：两室方案人数加总必须等于合排已座。"""
    plans = db.scalars(select(SeatPlan).where(SeatPlan.merge_id == merge_id).order_by(SeatPlan.id)).all()
    if not plans:
        raise HTTPException(404, "合排记录不存在")
    halls = []
    seated_sum = 0
    for p in plans:
        data = json.loads(p.result_json)
        stats = data.get("stats", {})
        seated_sum += stats.get("seated", 0)
        halls.append({"hall_id": p.hall_id, "plan_id": p.id, "stats": stats, "merge": data.get("merge")})
    merged_seated = (halls[0].get("merge") or {}).get("merged_seated")
    return {"merge_id": merge_id, "halls": halls, "seated_sum": seated_sum,
            "merged_seated": merged_seated, "balanced": seated_sum == merged_seated}
