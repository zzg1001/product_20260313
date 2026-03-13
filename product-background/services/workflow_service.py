from sqlalchemy.orm import Session
from typing import List, Optional
from models.workflow import Workflow
from schemas.workflow import WorkflowCreate, WorkflowUpdate


class WorkflowService:
    def __init__(self, db: Session):
        self.db = db

    def get_all(self) -> List[Workflow]:
        return self.db.query(Workflow).all()

    def get_by_id(self, workflow_id: str) -> Optional[Workflow]:
        return self.db.query(Workflow).filter(Workflow.id == workflow_id).first()

    def create(self, workflow_data: WorkflowCreate) -> Workflow:
        workflow = Workflow(
            id=workflow_data.id,
            name=workflow_data.name,
            description=workflow_data.description,
            icon=workflow_data.icon,
            nodes=workflow_data.nodes or [],
            edges=workflow_data.edges or []
        )
        self.db.add(workflow)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def update(self, workflow_id: str, workflow_data: WorkflowUpdate) -> Optional[Workflow]:
        workflow = self.get_by_id(workflow_id)
        if not workflow:
            return None

        update_data = workflow_data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(workflow, key, value)

        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def delete(self, workflow_id: str) -> bool:
        workflow = self.get_by_id(workflow_id)
        if not workflow:
            return False

        self.db.delete(workflow)
        self.db.commit()
        return True
