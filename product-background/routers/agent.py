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

router = APIRouter(prefix="/api/agent", tags=["Agent"])

# 上传目录
UPLOADS_DIR = Path(__file__).parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat with AI agent (non-streaming)"""
    service = AgentService(db)
    try:
        history = [{"role": m.role, "content": m.content} for m in request.history] if request.history else []
        response = await service.chat(
            message=request.message,
            history=history,
            skill_ids=request.skill_ids
        )
        return ChatResponse(message=response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """Chat with AI agent (streaming via SSE)"""
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
            yield "data: [DONE]\n\n"
        except Exception as e:
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
    print(f"\n{'='*60}")
    print(f"[Execute API] Incoming request for skill_id: {request.skill_id}")
    print(f"{'='*60}")
    print(f"[Execute API] Script name: {request.script_name}")
    print(f"[Execute API] Params keys: {list(request.params.keys()) if request.params else 'None'}")
    if request.params:
        context = request.params.get('context', '')
        print(f"[Execute API] Context: {context[:200] if context else 'NO CONTEXT'}...")

    service = AgentService(db)
    success, result, error, output = service.execute_skill(
        skill_id=request.skill_id,
        script_name=request.script_name,
        params=request.params
    )

    print(f"\n[Execute API] Execution completed:")
    print(f"[Execute API]   - Success: {success}")
    print(f"[Execute API]   - Error: {error}")
    print(f"[Execute API]   - Result type: {type(result)}")
    if result:
        result_str = str(result)
        print(f"[Execute API]   - Result preview: {result_str[:300]}{'...' if len(result_str) > 300 else ''}")

    # 生成输出文件
    output_file = None
    if success:
        # 获取技能信息用于生成文件
        from models.skill import Skill
        skill = db.query(Skill).filter(Skill.id == request.skill_id).first()
        print(f"[Execute API] Generating output file for skill: {skill.name if skill else 'None'}")
        if skill:
            try:
                # 获取技能的 output_config
                skill_output_config = skill.output_config if hasattr(skill, 'output_config') else None
                print(f"[Execute API] Skill output_config: {skill_output_config}")

                file_info = generate_output_file(
                    skill_name=skill.name,
                    skill_description=skill.description,
                    execution_result=result,
                    execution_output=output,
                    params=request.params,
                    output_config=skill_output_config  # 传递技能的输出配置
                )
                print(f"[Execute API] Generated file_info: {file_info}")
                if file_info:
                    output_file = OutputFile(**file_info)
            except Exception as e:
                import traceback
                print(f"[Execute API] ERROR generating output file: {e}")
                traceback.print_exc()
    else:
        # 执行失败时也打印详细信息
        print(f"\n[Execute API] ❌ Skill execution FAILED!")
        print(f"[Execute API] Error: {error}")
        if output:
            print(f"[Execute API] Output captured:\n{output}")

    print(f"[Execute API] Final output_file: {output_file}")
    print(f"{'='*60}\n")

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
