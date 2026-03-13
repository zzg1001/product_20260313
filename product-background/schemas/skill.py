from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime


class InteractionOption(BaseModel):
    value: str
    label: str


class SkillInteraction(BaseModel):
    id: str
    type: str  # input, select, multiselect, confirm, upload, form
    label: str
    description: Optional[str] = None
    required: bool = True
    timing: str = "before"  # before=可预收集, during=需运行时
    depends_on: Optional[str] = None
    options: Optional[List[InteractionOption]] = None
    validation: Optional[dict] = None


class OutputConfig(BaseModel):
    """技能输出文件配置"""
    enabled: bool = True  # 是否生成输出文件
    preferred_type: Optional[str] = None  # 优先文件类型: png, pdf, xlsx, docx, txt, json, html, md 等
    filename_template: Optional[str] = None  # 文件名模板，支持 {skill_name}, {timestamp}, {uuid}
    description: Optional[str] = None  # 输出说明


class SkillBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = "⚡"
    tags: Optional[List[str]] = []
    entry_script: Optional[str] = "main.py"
    author: Optional[str] = None
    version: Optional[str] = "1.0.0"
    interactions: Optional[List[SkillInteraction]] = []
    output_config: Optional[OutputConfig] = None  # 输出配置


class SkillCreate(SkillBase):
    """创建技能（手动创建，自动生成文件夹）"""
    code: Optional[str] = None  # 脚本代码，如果提供则自动创建文件夹


class SkillUpdate(BaseModel):
    """更新技能基本信息"""
    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    icon: Optional[str] = None
    tags: Optional[List[str]] = None
    entry_script: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = None
    interactions: Optional[List[SkillInteraction]] = None
    output_config: Optional[OutputConfig] = None  # 输出配置
    code: Optional[str] = None  # 更新脚本代码


class SkillResponse(BaseModel):
    """技能响应"""
    id: str  # UUID
    name: str
    description: Optional[str] = None
    icon: Optional[str] = None
    tags: Optional[List[str]] = None
    folder_path: Optional[str] = None
    entry_script: Optional[str] = None
    author: Optional[str] = None
    version: Optional[str] = None
    interactions: Optional[List[SkillInteraction]] = None
    output_config: Optional[OutputConfig] = None  # 输出配置
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
