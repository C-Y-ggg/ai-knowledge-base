from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime
from pgvector.sqlalchemy import Vector
from .database import Base

class Knowledge(Base):
    __tablename__ = "knowledge"
    id = Column(Integer, primary_key=True, index=True)
    file_name = Column(String, index=True)
    file_path = Column(String)
    parse_status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True, index=True)
    knowledge_id = Column(Integer, ForeignKey("knowledge.id"))
    content = Column(String)
    # 用来存 1024 维的数字向量（雷达柜）
    embedding = Column(Vector(1024))
    created_at = Column(DateTime, default=datetime.utcnow)