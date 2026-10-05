"""Exam seating: min Manhattan distance; same paper_id cannot be 4-neighbor adjacent."""
from __future__ import annotations

from dataclasses import asdict, dataclass


class MergeError(Exception):
    """合排无法成功完成（考生无法全部落座或对账自检失败）。调用方必须回滚双室全部改动。"""


@dataclass
class SeatAssign:
    candidate_id: int
    name: str
    ticket_no: str
    paper_id: int
    row: int
    col: int
    hall_id: int | None = None  # 合排时标识考生落座的考室区域；单室排座为 None


@dataclass
class Violation:
    kind: str
    a_id: int
    b_id: int
    detail: str


@dataclass
class RoomInput:
    hall_id: int
    rows: int
    cols: int
    min_manhattan: int
    candidates: list[dict]


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def neighbors4(r: int, c: int, rows: int, cols: int) -> list[tuple[int, int]]:
    out = []
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            out.append((nr, nc))
    return out


def _seat_acceptable(occ: dict[tuple[int, int], SeatAssign], rows: int, cols: int,
                     min_dist: int, cand: dict, r: int, c: int) -> bool:
    for (pr, pc), other in occ.items():
        if manhattan((r, c), (pr, pc)) < min_dist:
            return False
        if other.paper_id == cand["paper_id"] and (r, c) in neighbors4(pr, pc, rows, cols):
            return False
    for nr, nc in neighbors4(r, c, rows, cols):
        if (nr, nc) in occ and occ[(nr, nc)].paper_id == cand["paper_id"]:
            return False
    return True


def place_candidates(rows: int, cols: int, min_dist: int, candidates: list[dict]) -> tuple[list[SeatAssign], list[dict]]:
    """Greedy: try seats row-major; accept if manhattan >= min_dist to all placed AND no same paper 4-neigh."""
    occupied: dict[tuple[int, int], SeatAssign] = {}
    unplaced: list[dict] = []
    for cand in candidates:
        placed = False
        for r in range(rows):
            for c in range(cols):
                if (r, c) in occupied:
                    continue
                if not _seat_acceptable(occupied, rows, cols, min_dist, cand, r, c):
                    continue
                assign = SeatAssign(cand["id"], cand["name"], cand["ticket_no"], cand["paper_id"], r, c)
                occupied[(r, c)] = assign
                placed = True
                break
            if placed:
                break
        if not placed:
            unplaced.append(cand)
    return list(occupied.values()), unplaced


def find_violations(rows: int, cols: int, min_dist: int, assigns: list[SeatAssign]) -> list[Violation]:
    viols: list[Violation] = []
    by_pos = {(a.row, a.col): a for a in assigns}
    for i, a in enumerate(assigns):
        for b in assigns[i + 1:]:
            d = manhattan((a.row, a.col), (b.row, b.col))
            if d < min_dist:
                viols.append(Violation("distance", a.candidate_id, b.candidate_id,
                                       f"曼哈顿距离 {d} < 最小要求 {min_dist}"))
            if a.paper_id == b.paper_id and (b.row, b.col) in neighbors4(a.row, a.col, rows, cols):
                viols.append(Violation("same_paper_adjacent", a.candidate_id, b.candidate_id,
                                       f"同试卷套 {a.paper_id} 四邻相邻"))
    return viols


def plan_to_dict(assigns: list[SeatAssign], unplaced: list[dict], viols: list[Violation], rows: int, cols: int) -> dict:
    return {
        "rows": rows,
        "cols": cols,
        "assignments": [asdict(a) for a in assigns],
        "unplaced": unplaced,
        "violations": [asdict(v) for v in viols],
        "stats": {
            "seated": len(assigns),
            "unplaced": len(unplaced),
            "violations": len(viols),
            "capacity": rows * cols,
        },
    }


# ---------------------------------------------------------------- 两考室合排

def place_merged(room_a: RoomInput, room_b: RoomInput) -> dict:
    """两考室一次合排。

    规则：
    - 考生只能在自己所属考室的网格区域内落位（绝不跨室挪人，保证“考生不丢”）；
    - 间距/同卷四邻约束只在同一考室区域内判定，两室之间保持物理隔离；
    - 两室考生全局轮转依次尝试，体现“合在一起排”；
    - 任一考生无法落座即抛 MergeError —— 成功时不存在未排考生，由调用方整体提交，
      否则调用方必须双室回滚。
    返回含两室对账切片（room_slices）与合计统计的 payload。
    """
    rooms = [room_a, room_b]
    if room_a.hall_id == room_b.hall_id:
        raise MergeError("合排必须选择两间不同的考室")
    for room in rooms:
        if room.rows <= 0 or room.cols <= 0:
            raise MergeError(f"考室 {room.hall_id} 网格非法")
        if room.rows * room.cols < len(room.candidates):
            raise MergeError(
                f"考室 {room.hall_id} 容量 {room.rows * room.cols} 不足以容纳 {len(room.candidates)} 名考生，合排失败")

    occupied: dict[int, dict[tuple[int, int], SeatAssign]] = {rm.hall_id: {} for rm in rooms}
    queues: dict[int, list[dict]] = {rm.hall_id: list(rm.candidates) for rm in rooms}

    # 轮转：每轮各室出一名考生；考生只尝试本室座位
    while any(queues[rm.hall_id] for rm in rooms):
        for room in rooms:
            q = queues[room.hall_id]
            if not q:
                continue
            cand = q.pop(0)
            occ = occupied[room.hall_id]
            seated = False
            for r in range(room.rows):
                for c in range(room.cols):
                    if (r, c) in occ:
                        continue
                    if not _seat_acceptable(occ, room.rows, room.cols, room.min_manhattan, cand, r, c):
                        continue
                    occ[(r, c)] = SeatAssign(
                        cand["id"], cand["name"], cand["ticket_no"], cand["paper_id"], r, c, room.hall_id)
                    seated = True
                    break
                if seated:
                    break
            if not seated:
                # 任一考生无法落座即判定合排失败；成功路径不允许存在未排考生，由调用方双室回滚
                raise MergeError(f"合排失败：考生 {cand['id']} 无法在考室 {room.hall_id} 落座，双室回滚")

    slices = []
    for room in rooms:
        assigns = list(occupied[room.hall_id].values())
        viols = find_violations(room.rows, room.cols, room.min_manhattan, assigns)
        slice_payload = plan_to_dict(assigns, [], viols, room.rows, room.cols)
        slice_payload["hall_id"] = room.hall_id
        slice_payload["min_manhattan"] = room.min_manhattan
        slices.append(slice_payload)

    payload = {
        "merge": True,
        "room_slices": slices,
        "stats": {
            "seated": sum(s["stats"]["seated"] for s in slices),
            "unplaced": 0,
            "violations": sum(s["stats"]["violations"] for s in slices),
            "capacity": sum(s["stats"]["capacity"] for s in slices),
        },
    }
    _verify_merge_invariants(payload, rooms)
    return payload


def _verify_merge_invariants(payload: dict, rooms: list[RoomInput]) -> None:
    """提交前对账自检：任一不符即视为合排失败，调用方整体回滚。"""
    slices = payload["room_slices"]
    if len(slices) != 2:
        raise MergeError("合排对账失败：必须恰好两室")
    by_hall = {s["hall_id"]: s for s in slices}
    if set(by_hall) != {rm.hall_id for rm in rooms}:
        raise MergeError("合排对账失败：考室集合不一致")

    input_ids: dict[int, set[int]] = {rm.hall_id: {c["id"] for c in rm.candidates} for rm in rooms}
    total_seated = 0
    for rm in rooms:
        sl = by_hall[rm.hall_id]
        assigns = sl["assignments"]
        seated_ids = {a["candidate_id"] for a in assigns}
        # 考生不丢：本室输出考生集合必须等于输入集合（成功路径无未排）
        if seated_ids != input_ids[rm.hall_id]:
            raise MergeError(f"考室 {rm.hall_id} 对账失败：考生集合不一致")
        if len(seated_ids) != len(assigns):
            raise MergeError(f"考室 {rm.hall_id} 对账失败：存在重复落座")
        for a in assigns:
            if a["hall_id"] != rm.hall_id:
                raise MergeError(f"考室 {rm.hall_id} 对账失败：混入他室考生")
            if not (0 <= a["row"] < rm.rows and 0 <= a["col"] < rm.cols):
                raise MergeError(f"考室 {rm.hall_id} 对账失败：座位越界")
        if sl["stats"]["seated"] != len(assigns):
            raise MergeError(f"考室 {rm.hall_id} 统计与座位数不一致")
        total_seated += sl["stats"]["seated"]

    # 分室人数加总必须等于合排已座
    if total_seated != payload["stats"]["seated"]:
        raise MergeError("合排对账失败：分室人数加总不等于合排已座")
    all_input = sum((rm.candidates for rm in rooms), [])
    if total_seated != len(all_input) or len({c["id"] for c in all_input}) != len(all_input):
        raise MergeError("合排对账失败：合排已座与考生总数不符")
