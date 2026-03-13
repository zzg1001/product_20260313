from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from database import get_db
from services.execution_service import ExecutionService
from schemas.execution import (
    ExecutionStatus, StartExecutionRequest, InteractionResponse,
    WorkflowPreCheck
)

router = APIRouter(prefix="/api/executions", tags=["executions"])


@router.get("/workflow/{workflow_id}/precheck", response_model=WorkflowPreCheck)
async def precheck_workflow(workflow_id: str, db: Session = Depends(get_db)):
    """
    预检查工作流，返回所有需要预收集的交互
    在启动执行前调用，收集 timing=before 的交互输入
    """
    service = ExecutionService(db)
    result = service.precheck_workflow(workflow_id)
    if not result:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return result


@router.post("/workflow/{workflow_id}/start", response_model=ExecutionStatus)
async def start_execution(
    workflow_id: str,
    request: StartExecutionRequest = None,
    db: Session = Depends(get_db)
):
    """
    启动工作流执行
    pre_inputs: 预收集的交互输入 {"interaction_id": value}
    """
    print(f"[API] /workflow/{workflow_id}/start called")
    service = ExecutionService(db)
    try:
        pre_inputs = request.pre_inputs if request else None
        print(f"[API] Starting execution with pre_inputs={pre_inputs}")
        return service.start_execution(workflow_id, pre_inputs)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{execution_id}", response_model=ExecutionStatus)
async def get_execution_status(execution_id: str, db: Session = Depends(get_db)):
    """获取执行状态"""
    service = ExecutionService(db)
    status = service.get_execution_status(execution_id)
    if not status:
        raise HTTPException(status_code=404, detail="Execution not found")
    return status


@router.post("/{execution_id}/interact", response_model=ExecutionStatus)
async def submit_interaction(
    execution_id: str,
    response: InteractionResponse,
    db: Session = Depends(get_db)
):
    """
    提交交互响应，恢复执行
    """
    service = ExecutionService(db)
    try:
        return service.resume_execution(execution_id, response)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{execution_id}/cancel")
async def cancel_execution(execution_id: str, db: Session = Depends(get_db)):
    """取消执行"""
    service = ExecutionService(db)
    success = service.cancel_execution(execution_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel execution")
    return {"message": "Execution cancelled"}


@router.get("/", response_model=List[ExecutionStatus])
async def list_executions(
    workflow_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """列出执行记录"""
    service = ExecutionService(db)
    executions = service.list_executions(workflow_id, limit)
    return [service.get_execution_status(e.id) for e in executions]
