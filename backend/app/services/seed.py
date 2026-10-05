import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, PaperSet
from app.services.merge import run_merge

logger = logging.getLogger(__name__)


def seed_if_empty(db: Session) -> None:
    if (db.scalar(select(func.count()).select_from(Hall)) or 0) > 0:
        return
    hall1 = Hall(code="H101", name="一号考室", rows=5, cols=6, min_manhattan=2)
    hall2 = Hall(code="H102", name="二号考室", rows=4, cols=6, min_manhattan=2)
    hall3 = Hall(code="H103", name="三号考室", rows=4, cols=5, min_manhattan=2)
    db.add_all([hall1, hall2, hall3])
    db.flush()
    papers = [("P-A", "语文 A 卷"), ("P-B", "语文 B 卷"), ("P-C", "语文 C 卷")]
    paper_ids = []
    for code, title in papers:
        p = PaperSet(code=code, title=title)
        db.add(p); db.flush()
        paper_ids.append(p.id)
    names1 = ["陈一", "李二", "张三", "赵四", "钱五", "孙六", "周七", "吴八", "郑九", "王十", "冯十一", "陈十二"]
    names2 = ["刘一", "黄二", "徐三", "高四", "林五", "何六", "郭七", "马八", "罗九", "梁十"]
    names3 = ["宋一", "唐二", "许三", "韩四", "邓五", "曹六", "彭七", "萧八"]
    for hall, names, base in ((hall1, names1, 2026001), (hall2, names2, 2026101), (hall3, names3, 2026201)):
        for i, name in enumerate(names):
            db.add(Candidate(hall_id=hall.id, name=name, ticket_no=f"T{base+i}",
                             paper_id=paper_ids[i % len(paper_ids)]))
    db.commit()
    # 种子合排：一号 + 二号。成功则两室各留可对账方案；任一步失败则双室回滚、
    # 不留任何合排指针，基础数据保留；三号考室不参与、不被改动。
    try:
        run_merge(db, hall1.id, hall2.id)
    except Exception:
        db.rollback()
        logger.exception("种子合排失败，已双室回滚（无残留合排指针）")
