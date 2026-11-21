"""数据访问路由：按（项目×产品×用途）绑定资格实例，只放行该用途投影内的字段。

关键约束：
- 一次访问只绑定一个用途，绝不对该成员的多个用途/多个课题资格取并集；
- request_id 幂等：断线重试重复提交返回同一访问事件，额度只扣一次；
- 每次访问记录当时的产品定义、资格依据与额度变化快照，供审计还原。
"""
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    AccessEvent, DataProduct, Project, ProjectMember, QualificationInstance,
    QuotaReservation, UsageEvent, User,
)
from ..schemas import AccessQueryIn
from ..security import current_user, require_roles
from ..serializers import access_event_dict, product_dict
from ..services import quota as quota_svc
from ..services.quota import QuotaError

router = APIRouter(prefix="/api/access", tags=["数据访问"])

EXPORT_ROLES = {"PI", "数据分析师"}  # 可导出角色；研究员/统计师仅查询


def _product_snapshot(product: DataProduct) -> dict:
    d = product_dict(product, with_fields=True)
    d["snapshot_note"] = "访问发生时的产品目录定义快照"
    return d


def _qualification_snapshot(q: QualificationInstance) -> dict:
    return {
        "id": q.id, "purpose_code": q.purpose_code, "status": q.status,
        "valid_from": q.valid_from.isoformat(), "valid_to": q.valid_to.isoformat(),
        "catalog_version": q.catalog_version,
        "field_projection": q.field_projection,
        "covered_member_ids": q.covered_member_ids,
        "basis": q.basis,
    }


def _deny(db: Session, payload: AccessQueryIn, member, reason: str,
          product=None, qualification=None) -> dict:
    event = AccessEvent(
        request_id=payload.request_id,
        project_id=payload.project_id, product_id=payload.product_id,
        purpose_code=payload.purpose_code,
        member_id=member.id if member else None,
        member_name=member.name if member else "",
        qualification_id=qualification.id if qualification else None,
        kind=payload.kind, status="拒绝", deny_reason=reason,
        requested_fields=payload.requested_fields, granted_fields=[],
        product_snapshot=_product_snapshot(product) if product else {},
        qualification_snapshot=_qualification_snapshot(qualification) if qualification else {},
        quota_snapshot={},
    )
    db.add(event)
    db.commit()
    return {"event": access_event_dict(event, detail=True), "idempotent_replay": False}


@router.post("/query")
def access_query(
    payload: AccessQueryIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("PI", "ANALYST")),
):
    if payload.kind not in ("查询", "导出"):
        raise HTTPException(400, "kind 仅支持 查询/导出")

    # 幂等：同一 request_id 重试直接返回首次事件（额度不会重复扣减）
    existing = db.query(AccessEvent).filter(AccessEvent.request_id == payload.request_id).first()
    if existing is not None:
        return {"event": access_event_dict(existing, detail=True), "idempotent_replay": True}

    project = db.get(Project, payload.project_id)
    product = db.get(DataProduct, payload.product_id)
    if project is None or product is None:
        raise HTTPException(404, "课题或产品不存在")

    member = None
    if user.member_name:
        member = (
            db.query(ProjectMember)
            .filter(ProjectMember.project_id == project.id,
                    ProjectMember.name == user.member_name)
            .first()
        )
    if member is None:
        return _deny(db, payload, None, "当前用户不是该课题成员", product)

    today = date.today()
    qualification = (
        db.query(QualificationInstance)
        .filter(
            QualificationInstance.project_id == project.id,
            QualificationInstance.product_id == product.id,
            QualificationInstance.purpose_code == payload.purpose_code,
            QualificationInstance.status == "已签发",
        )
        .first()
    )
    if qualification is None:
        return _deny(db, payload, member,
                     f"无（{project.code} × {product.code} × {payload.purpose_code}）的已签发资格",
                     product)
    if not (qualification.valid_from <= today <= qualification.valid_to):
        return _deny(db, payload, member,
                     f"资格已过有效期（{qualification.valid_from}~{qualification.valid_to}）",
                     product, qualification)
    if member.id not in (qualification.covered_member_ids or []):
        return _deny(db, payload, member,
                     "成员不在该资格签发时的覆盖范围内", product, qualification)
    if member.status != "在职" or not (member.valid_from <= today <= member.valid_to):
        return _deny(db, payload, member, "成员已离任或不在任期内", product, qualification)

    if payload.kind == "导出":
        export_allowed = (qualification.basis or {}).get("purpose", {}).get("export_allowed", False)
        if not export_allowed:
            return _deny(db, payload, member, "该用途条件不允许导出", product, qualification)
        if member.role not in EXPORT_ROLES:
            return _deny(db, payload, member, f"角色「{member.role}」无导出权限", product, qualification)

    # 字段投影：只放行该用途实例投影内的字段（不与其他用途/课题取并集）
    projection = qualification.field_projection or []
    projection_names = {f["field_name"] for f in projection}
    if payload.requested_fields:
        unknown = sorted(set(payload.requested_fields) - projection_names)
        granted_names = [f for f in payload.requested_fields if f in projection_names]
    else:
        unknown = []
        granted_names = sorted(projection_names)
    granted = [f for f in projection if f["field_name"] in set(granted_names)]
    if not granted:
        return _deny(db, payload, member,
                     "所申请字段均不在该用途资格投影内" + (f"：{','.join(unknown)}" if unknown else ""),
                     product, qualification)

    # 额度：并发占用 + 消耗扣减（同事务，账户行锁串行化）
    reservation: QuotaReservation | None = None
    usage: UsageEvent | None = None
    try:
        reservation = quota_svc.acquire(db, project.id, payload.kind,
                                        note=f"访问请求 {payload.request_id}")
        usage_kind = "查询" if payload.kind == "查询" else "导出"
        amount = 1 if payload.kind == "查询" else payload.export_rows
        usage, _ = quota_svc.report_usage(
            db, project.id, usage_kind, amount,
            idempotency_key=f"access:{payload.request_id}",
            note=f"数据访问消耗（{payload.request_id}）",
        )
        quota_svc.release(db, reservation, status="已结算")
    except QuotaError as exc:
        if reservation is not None:
            quota_svc.release(db, reservation)
        return _deny(db, payload, member, f"额度校验未通过：{exc}", product, qualification)

    event = AccessEvent(
        request_id=payload.request_id,
        project_id=project.id, product_id=product.id,
        purpose_code=payload.purpose_code,
        member_id=member.id, member_name=member.name,
        qualification_id=qualification.id,
        kind=payload.kind, status="成功",
        requested_fields=payload.requested_fields,
        granted_fields=granted,
        product_snapshot=_product_snapshot(product),
        qualification_snapshot=_qualification_snapshot(qualification),
        quota_snapshot={
            "reservation_id": reservation.id,
            "usage_event_id": usage.id,
            "receipt_no": usage.receipt_no,
            "consumed": {"kind": usage.kind, "amount": usage.amount},
            "balance_after": usage.balance_after,
            "rejected_fields": unknown,
        },
    )
    db.add(event)
    db.flush()
    reservation.access_event_id = event.id
    usage.access_event_id = event.id
    db.commit()
    return {"event": access_event_dict(event, detail=True), "idempotent_replay": False}


@router.get("/events")
def list_events(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    q = db.query(AccessEvent).order_by(AccessEvent.id.desc())
    if user.role in ("PI", "ANALYST"):
        # 业务角色仅可见本课题的访问事件
        my_project_ids = [
            m.project_id for m in db.query(ProjectMember)
            .filter(ProjectMember.name == (user.member_name or "")).all()
        ]
        q = q.filter(AccessEvent.project_id.in_(my_project_ids or [-1]))
    if project_id:
        q = q.filter(AccessEvent.project_id == project_id)
    return [access_event_dict(e) for e in q.limit(100).all()]
