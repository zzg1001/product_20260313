import uuid
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import json
from database import get_db
from schemas.agent import (
    ChatRequest, ChatResponse,
    PlanRequest, PlanResponse,
    ExecuteRequest, ExecuteResponse, OutputFile
)
from services.agent_service import AgentService
from services.file_generator import generate_output_file
from routers.logs import (
    log_info, log_error,
    log_skill_start, log_skill_step, log_skill_success, log_skill_error,
    log_ai_start, log_ai_done, log_file_write,
    log_session_start, log_session_end
)

router = APIRouter(prefix="/api/agent", tags=["Agent"])

# 上传目录
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat with AI agent (non-streaming)"""
    # 记录会话上下文
    from models.skill import Skill
    skill_names = []
    if request.skill_ids:
        skills = db.query(Skill).filter(Skill.id.in_(request.skill_ids)).all()
        skill_names = [s.name for s in skills]

    log_session_start(
        api_name="POST /agent/chat",
        api_desc="与AI助手对话（非流式），AI会根据问题和技能给出回答",
        source="Agent对话页面",
        skills=skill_names if skill_names else None,
        user_input=request.message
    )

    service = AgentService(db)
    try:
        history = [{"role": m.role, "content": m.content} for m in request.history] if request.history else []
        log_ai_start(request.message[:100])
        response = await service.chat(
            message=request.message,
            history=history,
            skill_ids=request.skill_ids
        )
        log_ai_done(response[:100] if response else None)
        log_session_end(True, "AI响应完成")
        return ChatResponse(message=response)
    except Exception as e:
        log_error(f"聊天失败: {str(e)[:50]}")
        log_session_end(False, str(e)[:50])
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat with AI agent (streaming via SSE)"""
    # 记录会话上下文
    from models.skill import Skill
    skill_names = []
    if request.skill_ids:
        skills = db.query(Skill).filter(Skill.id.in_(request.skill_ids)).all()
        skill_names = [s.name for s in skills]

    log_session_start(
        api_name="POST /agent/chat/stream",
        api_desc="与AI助手实时对话（流式），文字会逐字显示",
        source="Agent对话页面",
        skills=skill_names if skill_names else None,
        user_input=request.message
    )
    log_ai_start(request.message[:100])

    service = AgentService(db)

    async def generate():
        try:
            history = [{"role": m.role, "content": m.content} for m in request.history] if request.history else []
            async for chunk in service.chat_stream(
                message=request.message,
                history=history,
                skill_ids=request.skill_ids
            ):
                yield f"data: {json.dumps({'content': chunk})}\n\n"
            log_ai_done()
            yield "data: [DONE]\n\n"
        except Exception as e:
            log_error(f"流式响应失败: {str(e)[:50]}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/plan", response_model=PlanResponse)
async def plan_skills(request: PlanRequest, db: Session = Depends(get_db)):
    """Plan which skills to use based on user input"""
    service = AgentService(db)
    try:
        plan_items, explanation = await service.plan_skills(
            user_input=request.user_input,
            available_skill_ids=request.available_skills
        )
        return PlanResponse(plan=plan_items, explanation=explanation)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/execute", response_model=ExecuteResponse)
async def execute_skill(request: ExecuteRequest, db: Session = Depends(get_db)):
    """Execute a skill's script"""
    from pathlib import Path
    from models.skill import Skill

    skill = db.query(Skill).filter(Skill.id == request.skill_id).first()
    skill_name = skill.name if skill else request.skill_id

    # 记录执行上下文
    log_session_start(
        api_name="POST /agent/execute",
        api_desc=f"执行技能脚本，运行 {skill_name} 完成具体任务",
        source="技能执行",
        skills=[skill_name]
    )

    # 【关键】处理文件路径：将相对路径转换为绝对路径
    params = dict(request.params) if request.params else {}
    base_dir = Path(__file__).parent.parent  # product-background 目录

    # 处理 file_path
    if params.get('file_path'):
        fp = params['file_path']
        if not Path(fp).is_absolute():
            abs_path = base_dir / fp
            if abs_path.exists():
                params['file_path'] = str(abs_path)
                print(f"[Execute] Converted file_path: {fp} -> {abs_path}")

    # 处理 file_paths 和 files 数组
    for key in ['file_paths', 'files']:
        if params.get(key) and isinstance(params[key], list):
            converted = []
            for fp in params[key]:
                if not Path(fp).is_absolute():
                    abs_path = base_dir / fp
                    if abs_path.exists():
                        converted.append(str(abs_path))
                        print(f"[Execute] Converted {key} item: {fp} -> {abs_path}")
                    else:
                        converted.append(fp)
                else:
                    converted.append(fp)
            params[key] = converted

    # 日志：开始（包含输入参数）
    log_skill_start(skill_name, params)

    # 调试：打印完整参数
    print(f"\n========== [Execute Skill] ==========")
    print(f"[Execute] skill_id: {request.skill_id}")
    print(f"[Execute] skill_name: {skill_name}")
    print(f"[Execute] params keys: {list(params.keys()) if params else 'None'}")
    print(f"[Execute] file_path: {params.get('file_path', 'NOT SET')}")
    print(f"[Execute] file_paths: {params.get('file_paths', 'NOT SET')}")
    print(f"[Execute] Full params: {params}")
    print(f"======================================\n")

    service = AgentService(db)
    log_skill_step(skill_name, "执行脚本", detail=f"script: {request.script_name}")

    success, result, error, output = service.execute_skill(
        skill_id=request.skill_id,
        script_name=request.script_name,
        params=params
    )

    # 生成输出文件
    output_file = None
    if success:
        log_skill_step(skill_name, "生成文件")

        if skill:
            try:
                skill_output_config = skill.output_config if hasattr(skill, 'output_config') else None
                file_info = generate_output_file(
                    skill_name=skill.name,
                    skill_description=skill.description,
                    execution_result=result,
                    execution_output=output,
                    params=request.params,
                    output_config=skill_output_config
                )
                if file_info:
                    output_file = OutputFile(**file_info)
                    log_file_write(file_info['name'], file_info.get('size'))
            except Exception:
                pass

        # 日志：完成（包含结果）
        log_skill_success(skill_name, result)
        log_session_end(True, f"技能 {skill_name} 执行成功")
    else:
        log_skill_error(skill_name, error or "未知错误")
        log_session_end(False, error or "未知错误")

    return ExecuteResponse(
        success=success,
        result=result,
        error=error,
        output=output,
        output_file=output_file
    )


@router.post("/execute-temp", response_model=ExecuteResponse)
async def execute_temp_skill(request: ExecuteRequest, db: Session = Depends(get_db)):
    """执行临时技能（用于测试）"""
    from pathlib import Path
    import json as json_lib

    temp_id = request.skill_id
    temp_skills_dir = Path(__file__).parent.parent / "skills_storage_temp"
    temp_folder = temp_skills_dir / temp_id

    if not temp_folder.exists():
        log_error("临时技能不存在", detail=f"ID: {temp_id}")
        return ExecuteResponse(success=False, error="临时技能不存在或已过期", output=None)

    # 读取配置
    config_path = temp_folder / "config.json"
    config = json_lib.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {"name": "temp_skill"}

    class TempSkill:
        def __init__(self, folder, cfg):
            self.id = temp_id
            self.name = cfg.get("name", "temp_skill")
            self.description = cfg.get("description", "")
            self.folder_path = str(folder)
            self.entry_script = cfg.get("entry_script")
            self.output_config = cfg.get("output_config")

    temp_skill = TempSkill(temp_folder, config)

    # 记录执行上下文
    log_session_start(
        api_name="POST /agent/execute-temp",
        api_desc=f"测试临时技能，验证 {temp_skill.name} 是否正常工作",
        source="技能测试页面",
        skills=[temp_skill.name]
    )

    # 日志：开始（包含输入参数）
    log_skill_start(f"[测试] {temp_skill.name}", request.params)

    service = AgentService(db)
    log_skill_step(temp_skill.name, "执行测试", detail=f"script: {request.script_name}")

    success, result, error, output = service.execute_temp_skill(
        temp_folder=temp_folder,
        skill_name=temp_skill.name,
        script_name=request.script_name,
        params=request.params
    )

    # 生成输出文件
    output_file = None
    if success:
        log_skill_step(temp_skill.name, "生成文件")
        try:
            file_info = generate_output_file(
                skill_name=temp_skill.name,
                skill_description=temp_skill.description,
                execution_result=result,
                execution_output=output,
                params=request.params,
                output_config=temp_skill.output_config
            )
            if file_info:
                output_file = OutputFile(**file_info)
                log_file_write(file_info['name'], file_info.get('size'))
        except Exception:
            pass

        log_skill_success(temp_skill.name, result)
        log_session_end(True, f"测试技能 {temp_skill.name} 执行成功")
    else:
        log_skill_error(temp_skill.name, error or "未知错误")
        log_session_end(False, error or "未知错误")

    return ExecuteResponse(
        success=success,
        result=result,
        error=error,
        output=output,
        output_file=output_file
    )


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    上传文件供技能处理使用

    支持的文件类型: Excel (.xlsx, .xls), CSV (.csv)
    返回文件路径，可传递给技能执行参数
    """
    # 验证文件类型
    allowed_extensions = {".xlsx", ".xls", ".csv", ".json", ".txt"}
    file_ext = Path(file.filename).suffix.lower() if file.filename else ""

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file_ext}。支持: {', '.join(allowed_extensions)}"
        )

    # 生成唯一文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_id = str(uuid.uuid4())[:8]
    safe_filename = f"upload_{timestamp}_{short_id}{file_ext}"
    filepath = UPLOADS_DIR / safe_filename

    # 保存文件
    try:
        content = await file.read()
        filepath.write_bytes(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {str(e)}")

    # 返回文件信息
    return {
        "success": True,
        "filename": safe_filename,
        "original_name": file.filename,
        "path": str(filepath),  # 绝对路径，供技能脚本使用
        "url": f"/uploads/{safe_filename}",  # 相对 URL
        "size": len(content),
        "type": file_ext.lstrip(".")
    }
