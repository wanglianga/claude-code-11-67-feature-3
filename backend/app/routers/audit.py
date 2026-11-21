"""审计路由：从一次数据访问还原当时的产品定义、资格依据与额度变化。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    AccessEvent, DataProduct, QualificationInstance, QuotaReservation,
    UsageEvent, UsageReport, User,
)
from ..security import require_roles
from ..serializers import access_event_dict, product_dict

router = APIRouter(prefix="/api/audit", tags=["审计查询"])


def _diff_catalog(then_fields: list[dict], now_fields: list[dict]) -> list[dict]:
    """对比访问当时与当前的产品字段定义，列出差异。"""
    now_by_name = {f["field_name"]: f for f in now_fields}
    then_by_name = {f["field_name"]: f for f in then_fields}
    diffs: list[dict] = []
    for name, then in then_by_name.items():
        now = now_by_name.get(name)
        if now is None:
            diffs.append({"field_name": name, "change": "字段已从目录中移除"})
            continue
        if then["sensitivity_level"] != now["sensitivity_level"]:
            diffs.append({
                "field_name": name,
                "change": f"敏感等级 L{then['sensitivity_level']} → L{now['sensitivity_level']}",
            })
        if sorted(then.get("tags", [])) != sorted(now.get("tags", [])):
            diffs.append({
                "field_name": name,
                "change": f"标签 {then.get('tags', [])} → {now.get('tags', [])}",
            })
        if (then["available_from"], then["available_to"]) != (now["available_from"], now["available_to"]):
            diffs.append({
                "field_name": name,
                "change": (f"可用期 {then['available_from']}~{then['available_to']} → "
                           f"{now['available_from']}~{now['available_to']}"),
            })
        if not now["is_active"]:
            diffs.append({"field_name": name, "change": "字段现已停用"})
    for name in sorted(set(now_by_name) - set(then_by_name)):
        diffs.append({"field_name": name, "change": "访问之后新增字段"})
    return diffs


@router.get("/access/{event_id}")
def audit_access(
    event_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN", "AUDITOR")),
):
    event = db.get(AccessEvent, event_id)
    if event is None:
        raise HTTPException(404, "访问事件不存在")

    product = db.get(DataProduct, event.product_id)
    product_now = product_dict(product, with_fields=True) if product else None
    then_fields = (event.product_snapshot or {}).get("fields", [])
    now_fields = (product_now or {}).get("fields", [])
    catalog_diff = _diff_catalog(then_fields, now_fields) if product_now else []

    qualification_now = None
    if event.qualification_id:
        q = db.get(QualificationInstance, event.qualification_id)
        if q is not None:
            qualification_now = {
                "id": q.id, "status": q.status,
                "revoked_at": q.revoked_at.isoformat() if q.revoked_at else None,
                "revoke_reason": q.revoke_reason,
            }

    quota = event.quota_snapshot or {}
    reservation = None
    usage = None
    reports: list[dict] = []
    if quota.get("reservation_id"):
        r = db.get(QuotaReservation, quota["reservation_id"])
        if r is not None:
            reservation = {
                "id": r.id, "kind": r.kind, "status": r.status,
                "created_at": r.created_at.isoformat(),
                "released_at": r.released_at.isoformat() if r.released_at else None,
            }
    if quota.get("usage_event_id"):
        u = db.get(UsageEvent, quota["usage_event_id"])
        if u is not None:
            usage = {
                "id": u.id, "kind": u.kind, "amount": u.amount,
                "idempotency_key": u.idempotency_key, "receipt_no": u.receipt_no,
                "balance_after": u.balance_after, "created_at": u.created_at.isoformat(),
            }
            reports = [
                {"id": x.id, "is_duplicate": x.is_duplicate, "note": x.note,
                 "reported_at": x.reported_at.isoformat()}
                for x in db.query(UsageReport).filter(UsageReport.event_id == u.id)
                .order_by(UsageReport.id).all()
            ]

    return {
        "event": access_event_dict(event, detail=True),
        "product_then": event.product_snapshot,
        "product_now": product_now,
        "catalog_diff": catalog_diff,
        "qualification_basis_then": event.qualification_snapshot,
        "qualification_now": qualification_now,
        "quota_trail": {
            "reservation": reservation,
            "usage_event": usage,
            "usage_reports": reports,
            "snapshot": quota,
        },
    }
