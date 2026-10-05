import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Candidate, Hall, PaperSet


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def SessionTest(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture()
def seeded(SessionTest):
    """三室 + 两间极小考室：H1/H2 可成功合排；H3 为不参与的第三室；H4 合排必失败。"""
    db = SessionTest()
    specs = [
        ("H101", "一号考室", 5, 6),
        ("H102", "二号考室", 4, 5),
        ("H103", "三号考室", 3, 4),
        ("H104", "四号考室", 1, 1),
        ("H105", "五号考室", 1, 2),  # 容量 2 但 min_dist=2：两人间距 1，排座本身必失败
    ]
    hall_ids = []
    for code, name, rows, cols in specs:
        h = Hall(code=code, name=name, rows=rows, cols=cols, min_manhattan=2)
        db.add(h)
        db.flush()
        hall_ids.append(h.id)
    pids = []
    for code in ("P-A", "P-B", "P-C"):
        p = PaperSet(code=code, title=code)
        db.add(p)
        db.flush()
        pids.append(p.id)
    counts = {hall_ids[0]: 12, hall_ids[1]: 8, hall_ids[2]: 5, hall_ids[3]: 2, hall_ids[4]: 2}
    seq = 1
    for hid, n in counts.items():
        for _ in range(n):
            db.add(Candidate(hall_id=hid, name=f"考生{seq}", ticket_no=f"T{seq}",
                             paper_id=pids[seq % len(pids)]))
            seq += 1
    db.commit()
    db.close()
    return hall_ids


@pytest.fixture()
def client_factory(SessionTest):
    """返回一个用指定 session 类覆盖 get_db 的 TestClient 工厂。"""
    from fastapi.testclient import TestClient

    def _factory(session_cls=None):
        cls = session_cls or SessionTest

        def _override_get_db():
            db = cls()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = _override_get_db
        return TestClient(app)

    yield _factory
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client(client_factory):
    return client_factory()
