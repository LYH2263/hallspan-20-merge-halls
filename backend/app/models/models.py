from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Hall(Base):
    __tablename__ = "halls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    rows: Mapped[int] = mapped_column(Integer)
    cols: Mapped[int] = mapped_column(Integer)
    min_manhattan: Mapped[int] = mapped_column(Integer, default=2)
    # 合排统一指针：为空=独立考室；非空=本室属于以 merged_into 为主室的合排（两室指向同一主室）
    merged_into: Mapped[int | None] = mapped_column(ForeignKey("halls.id"), nullable=True)

class PaperSet(Base):
    __tablename__ = "paper_sets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(128))

class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    name: Mapped[str] = mapped_column(String(64))
    ticket_no: Mapped[str] = mapped_column(String(32))
    paper_id: Mapped[int] = mapped_column(ForeignKey("paper_sets.id"))

class SeatPlan(Base):
    __tablename__ = "seat_plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hall_id: Mapped[int] = mapped_column(ForeignKey("halls.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    # 非空表示该方案是一次两室合排中本室的对账切片；两室两行共享同一 merge_key
    merge_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 已座人数冗余列，供数据库触发器在不解析 JSON 的情况下校验“有指针必有座位”
    seated_count: Mapped[int] = mapped_column(Integer, default=0)

# 触发器 DDL 在 app/services/integrity.py 中按方言注册到 metadata，create_all 时自动安装
from app.services import integrity  # noqa: E402,F401
