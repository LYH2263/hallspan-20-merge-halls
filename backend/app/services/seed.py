from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.models.models import Candidate, Hall, PaperSet


def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Hall)) or 0) > 0:
        return
    halls_spec = [
        Hall(code="H101", name="一号考室", rows=5, cols=6, min_manhattan=2),
        Hall(code="H102", name="二号考室", rows=4, cols=5, min_manhattan=2),
        Hall(code="H103", name="三号考室", rows=3, cols=4, min_manhattan=2),
    ]
    hall_ids = []
    for hall in halls_spec:
        db.add(hall)
        db.flush()
        hall_ids.append(hall.id)
    papers = [("P-A", "语文 A 卷"), ("P-B", "语文 B 卷"), ("P-C", "语文 C 卷")]
    paper_ids = []
    for code, title in papers:
        p = PaperSet(code=code, title=title)
        db.add(p)
        db.flush()
        paper_ids.append(p.id)
    surnames = ["陈", "李", "张", "赵", "钱", "孙", "周", "吴", "郑", "王", "冯", "褚"]
    given = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十",
             "十一", "十二", "十三", "十四", "十五", "十六", "十七", "十八", "十九", "二十",
             "廿一", "廿二", "廿三", "廿四", "廿五"]
    # 一/二号考室各 12/8 人，间距 2 网格均可全部落座，支持两室合排成功演示；三号考室 5 人
    counts = {hall_ids[0]: 12, hall_ids[1]: 8, hall_ids[2]: 5}
    ticket_seq = 2026001
    name_idx = 0
    for hall_id, count in counts.items():
        for _ in range(count):
            name = surnames[name_idx % len(surnames)] + given[name_idx]
            db.add(Candidate(hall_id=hall_id, name=name, ticket_no=f"T{ticket_seq}",
                             paper_id=paper_ids[name_idx % len(paper_ids)]))
            ticket_seq += 1
            name_idx += 1
    db.commit()
