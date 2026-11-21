"""资格开通路由：批次处理（逐项独立状态）、资格实例查询与撤回。"""
import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    DataProduct, Project, QualificationBatch, QualificationInstance, User,
)
from ..schemas import BatchCreateIn, RevokeIn
from ..security import current_user, require_roles
from ..serializers import batch_dict, qualification_dict
from ..services.compiler import CompileError, compile_qualification

router = APIRouter(prefix="/api/qualifications", tags=["资格开通"])


def _active_qualification(db: Session, project_id: int, product_id: int, purpose_code: str):
    return (
        db.query(QualificationInstance)
        .filter(
            QualificationInstance.project_id == project_id,
            QualificationInstance.product_id == product_id,
            QualificationInstance.purpose_code == purpose_code,
            QualificationInstance.status == "已签发",
        )
        .first()
    )


@router.post("/batches")
def create_batch(
    payload: BatchCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PI")),
):
    """开通批次：逐项编译（项目×产品×用途），每项实时重查伦理状态。

    - 任一单项失败不影响其他项；批次状态 = 完成 / 部分完成 / 失败，绝不整体假报成功。
    - 伦理在处理中失效的项不得签发，标记为「签发失败」并记录原因。
    """
    if not payload.items:
        raise HTTPException(400, "批次至少包含一项")

    # 预先校验外键，非法 id 直接拒绝整个请求（不产生半成品批次）
    for item in payload.items:
        if db.get(Project, item.project_id) is None:
            raise HTTPException(400, f"课题 id={item.project_id} 不存在")
        if db.get(DataProduct, item.product_id) is None:
            raise HTTPException(400, f"产品 id={item.product_id} 不存在")

    today = date.today()
    batch = QualificationBatch(
        batch_no="B" + uuid.uuid4().hex[:12].upper(),
        title=payload.title or "资格开通批次",
        total=len(payload.items),
        created_by=user.username,
    )
    db.add(batch)
    db.flush()

    for item in payload.items:
        project = db.get(Project, item.project_id)
        product = db.get(DataProduct, item.product_id)

        existing = _active_qualification(db, item.project_id, item.product_id, item.purpose_code)
        if existing is not None:
            db.add(QualificationInstance(
                batch_id=batch.id, project_id=project.id, product_id=product.id,
                purpose_code=item.purpose_code, status="签发失败",
                fail_reason=f"已存在已签发资格实例 #{existing.id}，如需变更请先撤回",
                valid_from=today, valid_to=today, issued_by=user.username,
            ))
            batch.failed += 1
            continue

        try:
            compiled = compile_qualification(db, project, product, item.purpose_code, today)
        except CompileError as exc:
            db.add(QualificationInstance(
                batch_id=batch.id, project_id=project.id, product_id=product.id,
                purpose_code=item.purpose_code, status="签发失败",
                fail_reason=str(exc),
                valid_from=today, valid_to=today, issued_by=user.username,
            ))
            batch.failed += 1
            continue

        db.add(QualificationInstance(
            batch_id=batch.id, project_id=project.id, product_id=product.id,
            purpose_code=item.purpose_code, status="已签发",
            field_projection=compiled.field_projection,
            covered_member_ids=compiled.covered_member_ids,
            basis=compiled.basis,
            catalog_version=compiled.catalog_version,
            valid_from=compiled.valid_from, valid_to=compiled.valid_to,
            issued_by=user.username,
        ))
        batch.succeeded += 1

    if batch.failed == 0:
        batch.status = "完成"
    elif batch.succeeded == 0:
        batch.status = "失败"
    else:
        batch.status = "部分完成"
    batch.finished_at = datetime.utcnow()
    db.commit()
    return batch_dict(batch, with_items=True)


@router.get("/batches")
def list_batches(db: Session = Depends(get_db), _: User = Depends(current_user)):
    batches = db.query(QualificationBatch).order_by(QualificationBatch.id.desc()).limit(100).all()
    return [batch_dict(b) for b in batches]


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    batch = db.get(QualificationBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    return batch_dict(batch, with_items=True)


@router.get("")
def list_qualifications(
    project_id: int | None = None,
    product_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    q = db.query(QualificationInstance).order_by(QualificationInstance.id.desc())
    if project_id:
        q = q.filter(QualificationInstance.project_id == project_id)
    if product_id:
        q = q.filter(QualificationInstance.product_id == product_id)
    if status:
        q = q.filter(QualificationInstance.status == status)
    return [qualification_dict(x) for x in q.limit(200).all()]


@router.get("/{qualification_id}")
def qualification_detail(
    qualification_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    q = db.get(QualificationInstance, qualification_id)
    if q is None:
        raise HTTPException(404, "资格实例不存在")
    return qualification_dict(q, detail=True)


@router.post("/{qualification_id}/revoke")
def revoke_qualification(
    qualification_id: int,
    payload: RevokeIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PI")),
):
    """撤回单个资格实例：只影响本（项目×产品×用途），不波及其他实例。"""
    q = db.get(QualificationInstance, qualification_id)
    if q is None:
        raise HTTPException(404, "资格实例不存在")
    if q.status != "已签发":
        raise HTTPException(400, f"当前状态为「{q.status}」，不能撤回")
    q.status = "已撤回"
    q.revoked_at = datetime.utcnow()
    q.revoke_reason = payload.reason or "人工撤回"
    db.commit()
    return qualification_dict(q, detail=True)
