import pytest

from app.services.seat_engine import MergeError, RoomInput, manhattan, place_merged


def _room(hid, rows, cols, ids, min_dist=2):
    return RoomInput(
        hall_id=hid, rows=rows, cols=cols, min_manhattan=min_dist,
        candidates=[{"id": i, "name": f"C{i}", "ticket_no": f"T{i}", "paper_id": 1 + (i % 2)}
                    for i in ids],
    )


def test_merge_success_seats_everyone_within_own_room():
    a = _room(1, 5, 6, range(1, 13))
    b = _room(2, 4, 5, range(101, 109))
    payload = place_merged(a, b)

    assert payload["merge"] is True
    slices = {s["hall_id"]: s for s in payload["room_slices"]}
    # 考生不丢：只在本室区域落位，人数与人员集合完全一致
    assert {x["candidate_id"] for x in slices[1]["assignments"]} == set(range(1, 13))
    assert {x["candidate_id"] for x in slices[2]["assignments"]} == set(range(101, 109))
    assert all(x["hall_id"] == 1 for x in slices[1]["assignments"])
    assert all(x["hall_id"] == 2 for x in slices[2]["assignments"])
    # 分室人数加总等于合排已座
    assert sum(s["stats"]["seated"] for s in payload["room_slices"]) == payload["stats"]["seated"]
    assert payload["stats"]["seated"] == 20
    assert payload["stats"]["unplaced"] == 0


def test_merge_respects_distance_and_adjacency():
    a = _room(1, 6, 6, range(1, 13))
    b = _room(2, 6, 6, range(101, 109))
    payload = place_merged(a, b)
    for s in payload["room_slices"]:
        assigns = s["assignments"]
        for i, x in enumerate(assigns):
            for y in assigns[i + 1:]:
                assert manhattan((x["row"], x["col"]), (y["row"], y["col"])) >= 2
                if x["paper_id"] == y["paper_id"]:
                    assert manhattan((x["row"], x["col"]), (y["row"], y["col"])) != 1


def test_merge_failure_raises_and_returns_nothing():
    # 四号考室 1x1 容纳 2 人：合排必失败，调用方拿不到任何部分结果
    a = _room(1, 5, 6, range(1, 13))
    b = _room(4, 1, 1, range(201, 203))
    with pytest.raises(MergeError):
        place_merged(a, b)


def test_merge_rejects_same_hall():
    a = _room(1, 5, 6, range(1, 4))
    with pytest.raises(MergeError):
        place_merged(a, a)
