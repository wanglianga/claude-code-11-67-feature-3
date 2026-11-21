"""课题档案路由：课题、用途条件、成员、伦理批件。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import EthicsApproval, Project, User
from ..schemas import RevokeIn
from ..security import current_user, require_roles
from ..serializers import ethics_dict, project_dict

router = APIRouter(prefix="/api/projects", tags=["课题档案"])


@router.get("")
def list_projects(db: Session = Depends(get_db), _: User = Depends(current_user)):
    projects = db.query(Project).order_by(Project.id).all()
    return [project_dict(p) for p in projects]


@router.get("/{project_id}")
def project_detail(project_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "课题不存在")
    return project_dict(project, detail=True)


@router.post("/{project_id}/ethics/{ethics_id}/revoke")
def revoke_ethics(
    project_id: int,
    ethics_id: int,
    payload: RevokeIn,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN")),
):
    """伦理批件失效：此后新资格编译将拒绝；已签发实例需另行撤回（状态相互独立）。"""
    ethics = db.get(EthicsApproval, ethics_id)
    if ethics is None or ethics.project_id != project_id:
        raise HTTPException(404, "伦理批件不存在")
    ethics.status = "失效"
    db.commit()
    return ethics_dict(ethics)


@router.post("/{project_id}/ethics/{ethics_id}/restore")
def restore_ethics(
    project_id: int,
    ethics_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN")),
):
    ethics = db.get(EthicsApproval, ethics_id)
    if ethics is None or ethics.project_id != project_id:
        raise HTTPException(404, "伦理批件不存在")
    ethics.status = "有效"
    db.commit()
    return ethics_dict(ethics)
