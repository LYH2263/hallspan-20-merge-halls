from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.models import Candidate, Hall
from app.services.seed import seed_if_empty


def test_seed_creates_three_halls(engine):
    SessionTest = sessionmaker(bind=engine)
    db = SessionTest()
    try:
        seed_if_empty(db)
        halls = db.scalars(select(Hall).order_by(Hall.id)).all()
        assert len(halls) == 3
        # 初始无合排指针
        assert all(h.merged_into is None for h in halls)
        counts = [db.scalar(select(func.count()).select_from(Candidate).where(Candidate.hall_id == h.id))
                  for h in halls]
        assert counts == [12, 8, 5]
        # 幂等：再次播种不重复
        seed_if_empty(db)
        assert db.scalar(select(func.count()).select_from(Hall)) == 3
    finally:
        db.close()
