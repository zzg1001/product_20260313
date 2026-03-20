from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Message]] = []
    skill_ids: Optional[List[str]] = None  # Available skills for this conversation


class ChatResponse(BaseModel):
    message: str
    skill_suggestions: Optional[List[Dict[str, Any]]] = None


class SkillPlanItem(BaseModel):
    skill_id: str  # UUID
    skill_name: str
    reason: str
    params: Optional[Dict[str, Any]] = {}


class PlanRequest(BaseModel):
    user_input: str
    available_skills: Optional[List[str]] = None


class PlanResponse(BaseModel):
    plan: List[SkillPlanItem]
    explanation: str


class ExecuteRequest(BaseModel):
    skill_id: str  # UUID
    script_name: Optional[str] = None  # If not specified, use entry_script
    params: Optional[Dict[str, Any]] = {}


class OutputFile(BaseModel):
    """输出文件信息"""
    name: str  # 文件名
    type: str  # 文件类型: pdf, excel, word, html, png, markdown, code, file
    url: str   # 下载URL
    size: Optional[str] = None  # 文件大小描述


class ExecuteResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    output: Optional[str] = None
    output_file: Optional[OutputFile] = None  # 输出文件


class AnalyzeRequest(BaseModel):
    """迭代分析请求"""
    file_paths: List[str]  # 要分析的文件路径列表
    context: Optional[str] = ""  # 用户需求描述
    skill_id: Optional[str] = None  # 可选的技能ID
    max_iterations: Optional[int] = 5  # 最大迭代次数


class AnalyzeCodeResult(BaseModel):
    """代码执行结果"""
    code: str  # 执行的代码
    success: bool
    stdout: str
    stderr: Optional[str] = None
    generated_files: Optional[List[Dict[str, Any]]] = []


class AnalyzeResponse(BaseModel):
    """迭代分析响应"""
    success: bool
    iterations: List[AnalyzeCodeResult] = []  # 每轮迭代结果
    final_report: Optional[str] = None  # 最终报告
    generated_files: Optional[List[Dict[str, Any]]] = []  # 所有生成的文件
    error: Optional[str] = None
