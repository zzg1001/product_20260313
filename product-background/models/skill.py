from sqlalchemy import Column, String, Text, DateTime, JSON, Boolean
from sqlalchemy.sql import func
from database import Base


class Skill(Base):
    __tablename__ = "skills"

    id = Column(String(36), primary_key=True)  # UUID
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(50), nullable=True, default="⚡")
    tags = Column(JSON, nullable=True, default=list)
    folder_path = Column(String(255), nullable=True)  # 技能文件夹相对路径
    entry_script = Column(String(100), nullable=True, default="main.py")  # 入口脚本
    author = Column(String(50), nullable=True)
    version = Column(String(20), nullable=True, default="1.0.0")
    interactions = Column(JSON, nullable=True, default=list)  # 交互配置
    # 输出配置
    output_config = Column(JSON, nullable=True, default=dict)  # 输出文件配置
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
