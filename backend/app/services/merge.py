"""两考室合排：单次事务，双室同成同败。

成功：两室各落一条带同一 merge_id 的可对账方案，考生不丢。
任一步失败：双室方案/统计/未排整体退回合排前，不留合排指针，第三室不受影响。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, SeatPlan
from app.services.seat_engine import merge_plan


class MergeError(Exception):
    """合排业务失败（抛出前保证双室无任何残留写入）。"""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _hall_candidates(db: Session, hall_id: int) -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
        for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id)).all()
    ]


def run_merge(db: Session, hall_a_id: int, hall_b_id: int) -> dict:
    """两考室合排一次。全部校验与计算先于任何写入；两条方案在同一事务提交。"""
    if hall_a_id == hall_b_id:
        raise MergeError("同一考室不能与自己合排")
    hall_a = db.get(Hall, hall_a_id)
    hall_b = db.get(Hall, hall_b_id)
    if hall_a is None:
        raise MergeError(f"考室 {hall_a_id} 不存在", 404)
    if hall_b is None:
        raise MergeError(f"考室 {hall_b_id} 不存在", 404)
    cands_a = _hall_candidates(db, hall_a_id)
    cands_b = _hall_candidates(db, hall_b_id)
    if not cands_a or not cands_b:
        raise MergeError("考室无考生，不能合排")

    try:
        merged = merge_plan(
            hall_a.rows, hall_a.cols, hall_a.min_manhattan, cands_a,
            hall_b.rows, hall_b.cols, hall_b.min_manhattan, cands_b,
        )
    except ValueError as exc:
        # 计算阶段失败：尚未写入任何方案，双室保持合排前状态
        raise MergeError(f"合排失败：{exc}") from exc

    merge_id = uuid4().hex
    now = datetime.utcnow()
    plans = []
    for hall, tag, partner in ((hall_a, "a", hall_b), (hall_b, "b", hall_a)):
        result = {
            "rows": hall.rows,
            "cols": hall.cols,
            "assignments": merged[f"assignments_{tag}"],
            "unplaced": merged[f"unplaced_{tag}"],
            "violations": merged[f"violations_{tag}"],
            "stats": merged[f"stats_{tag}"],
            "hall": {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan},
            "merge": {
                "merge_id": merge_id,
                "role": tag,
                "partner_hall_id": partner.id,
                "partner_hall_name": partner.name,
                "merged_seated": merged["merged_stats"]["seated"],
                "merged_unplaced": merged["merged_stats"]["unplaced"],
                "merged_violations": merged["merged_stats"]["violations"],
                "merged_capacity": merged["merged_stats"]["capacity"],
            },
        }
        plans.append(SeatPlan(hall_id=hall.id, merge_id=merge_id, created_at=now,
                              result_json=json.dumps(result, ensure_ascii=False)))

    db.add(plans[0])
    db.add(plans[1])
    try:
        db.commit()  # 单事务：两室方案同成同败，未参与的第三室不被触碰
    except Exception:
        db.rollback()  # 双室方案/统计/未排全部退回合排前，无残留合排指针
        raise
    for p in plans:
        db.refresh(p)
    return {
        "merge_id": merge_id,
        "grid": merged["grid"],
        "merged": merged["merged_stats"],
        "halls": [
            {"hall_id": hall_a.id, "plan_id": plans[0].id, "stats": merged["stats_a"]},
            {"hall_id": hall_b.id, "plan_id": plans[1].id, "stats": merged["stats_b"]},
        ],
    }
