from sqlalchemy import Column, String, Text, DateTime, JSON
from sqlalchemy.sql import func
from database import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String(50), primary_key=True)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True)
    nodes = Column(JSON, nullable=True, default=list)
    edges = Column(JSON, nullable=True, default=list)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
