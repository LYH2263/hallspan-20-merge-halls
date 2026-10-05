"""Exam seating: min Manhattan distance; same paper_id cannot be 4-neighbor adjacent."""
from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass
class SeatAssign:
    candidate_id: int
    name: str
    ticket_no: str
    paper_id: int
    row: int
    col: int

@dataclass
class Violation:
    kind: str
    a_id: int
    b_id: int
    detail: str

def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def neighbors4(r: int, c: int, rows: int, cols: int) -> list[tuple[int, int]]:
    out = []
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            out.append((nr, nc))
    return out

def place_candidates(rows: int, cols: int, min_dist: int, candidates: list[dict],
                     blocked: set[tuple[int, int]] | None = None,
                     initial: list[SeatAssign] | None = None) -> tuple[list[SeatAssign], list[dict]]:
    """Greedy: try seats row-major; accept if manhattan >= min_dist to all placed AND no same paper 4-neigh.

    blocked: seats that may never be used; initial: seats already occupied (constraints
    are enforced against them, but they are not part of the returned assignments).
    """
    occupied: dict[tuple[int, int], SeatAssign] = {}
    for a in initial or []:
        occupied[(a.row, a.col)] = a
    blocked = blocked or set()
    assigns: list[SeatAssign] = []
    unplaced: list[dict] = []
    for cand in candidates:
        placed = False
        for r in range(rows):
            for c in range(cols):
                if (r, c) in occupied or (r, c) in blocked:
                    continue
                ok = True
                for pos, other in occupied.items():
                    if manhattan((r, c), pos) < min_dist:
                        ok = False
                        break
                    if other.paper_id == cand["paper_id"] and (r, c) in neighbors4(pos[0], pos[1], rows, cols):
                        ok = False
                        break
                if not ok:
                    continue
                # also check 4-neigh same paper against current neighbors
                for nr, nc in neighbors4(r, c, rows, cols):
                    if (nr, nc) in occupied and occupied[(nr, nc)].paper_id == cand["paper_id"]:
                        ok = False
                        break
                if not ok:
                    continue
                assign = SeatAssign(cand["id"], cand["name"], cand["ticket_no"], cand["paper_id"], r, c)
                occupied[(r, c)] = assign
                assigns.append(assign)
                placed = True
                break
            if placed:
                break
        if not placed:
            unplaced.append(cand)
    return assigns, unplaced

def find_violations(rows: int, cols: int, min_dist: int, assigns: list[SeatAssign]) -> list[Violation]:
    viols: list[Violation] = []
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

def _assert_conserved(assigns: list[SeatAssign], unplaced: list[dict], cands: list[dict], label: str) -> None:
    """Each hall's seated + unplaced ids must be exactly its own candidate ids (考生不丢)."""
    got = sorted([a.candidate_id for a in assigns] + [c["id"] for c in unplaced])
    if got != sorted(c["id"] for c in cands):
        raise ValueError(f"合排考生守恒校验失败（{label} 室）")

def merge_plan(rows_a: int, cols_a: int, min_a: int, cands_a: list[dict],
               rows_b: int, cols_b: int, min_b: int, cands_b: list[dict]) -> dict:
    """两考室合排（纯函数，不落库）。

    B 室网格拼在 A 室下方，列数取两者较大值；窄室缺列的悬空格不可落座。
    两室考生各自只落在本室区域，但间距与同卷四邻约束跨室界生效。
    任一室无人入座或考生守恒被破坏时抛 ValueError —— 调用方必须整体回滚，
    禁止一室成功一室空，也禁止留下合排指针却没有座位。
    """
    ids_a = [c["id"] for c in cands_a]
    ids_b = [c["id"] for c in cands_b]
    if set(ids_a) & set(ids_b):
        raise ValueError("两考室存在考生重复")
    cols = max(cols_a, cols_b)
    rows = rows_a + rows_b
    min_dist = max(min_a, min_b)
    band_a = {(r, c) for r in range(rows_a) for c in range(cols)}
    band_b = {(r, c) for r in range(rows_a, rows) for c in range(cols)}
    overhang_a = {(r, c) for r in range(rows_a) for c in range(cols_a, cols)}
    overhang_b = {(r, c) for r in range(rows_a, rows) for c in range(cols_b, cols)}
    assigns_a, unplaced_a = place_candidates(rows, cols, min_dist, cands_a,
                                             blocked=band_b | overhang_a)
    assigns_b, unplaced_b = place_candidates(rows, cols, min_dist, cands_b,
                                             blocked=band_a | overhang_b, initial=assigns_a)
    if not assigns_a or not assigns_b:
        raise ValueError("合排后存在无座位的考室")
    _assert_conserved(assigns_a, unplaced_a, cands_a, "A")
    _assert_conserved(assigns_b, unplaced_b, cands_b, "B")
    assigns_b_local = [SeatAssign(a.candidate_id, a.name, a.ticket_no, a.paper_id,
                                  a.row - rows_a, a.col) for a in assigns_b]
    viols = find_violations(rows, cols, min_dist, assigns_a + assigns_b)
    region = {a.candidate_id: "a" for a in assigns_a}
    region.update({a.candidate_id: "b" for a in assigns_b})
    viols_a = [v for v in viols if region.get(v.a_id) == "a" or region.get(v.b_id) == "a"]
    viols_b = [v for v in viols if region.get(v.a_id) == "b" or region.get(v.b_id) == "b"]
    stats_a = {"seated": len(assigns_a), "unplaced": len(unplaced_a),
               "violations": len(viols_a), "capacity": rows_a * cols_a}
    stats_b = {"seated": len(assigns_b), "unplaced": len(unplaced_b),
               "violations": len(viols_b), "capacity": rows_b * cols_b}
    merged_stats = {
        "seated": stats_a["seated"] + stats_b["seated"],
        "unplaced": stats_a["unplaced"] + stats_b["unplaced"],
        "violations": len(viols),
        "capacity": stats_a["capacity"] + stats_b["capacity"],
    }
    return {
        "grid": {"rows": rows, "cols": cols, "min_dist": min_dist},
        "assignments_a": [asdict(a) for a in assigns_a],
        "assignments_b": [asdict(a) for a in assigns_b_local],
        "unplaced_a": unplaced_a,
        "unplaced_b": unplaced_b,
        "violations_a": [asdict(v) for v in viols_a],
        "violations_b": [asdict(v) for v in viols_b],
        "stats_a": stats_a,
        "stats_b": stats_b,
        "merged_stats": merged_stats,
    }
