"""额度账本路由：账户、并发占用、用量上报（幂等）与回执查询。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import QuotaAccount, QuotaReservation, UsageEvent, UsageReport, User
from ..schemas import ReservationIn, UsageReportIn
from ..security import current_user, require_roles
from ..serializers import (
    account_dict, reservation_dict, usage_event_dict, usage_report_dict,
)
from ..services import quota as quota_svc
from ..services.quota import QuotaError

router = APIRouter(prefix="/api/quota", tags=["额度账本"])


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db), _: User = Depends(current_user)):
    accounts = db.query(QuotaAccount).order_by(QuotaAccount.id).all()
    return [
        account_dict(a, active=quota_svc.active_reservations(db, a.id))
        for a in accounts
    ]


@router.get("/reservations")
def list_reservations(
    status: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    q = db.query(QuotaReservation).order_by(QuotaReservation.id.desc())
    if status:
        q = q.filter(QuotaReservation.status == status)
    return [reservation_dict(r) for r in q.limit(100).all()]


@router.post("/reservations")
def acquire_reservation(
    payload: ReservationIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PI", "ANALYST")),
):
    """手动占用一个并发槽（用于演示/压测并发占用上限）。"""
    try:
        r = quota_svc.acquire(db, payload.project_id, payload.kind,
                              note=payload.note or f"手动占用 by {user.username}")
    except QuotaError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    return reservation_dict(r)


@router.post("/reservations/{reservation_id}/release")
def release_reservation(
    reservation_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles("ADMIN", "PI", "ANALYST")),
):
    r = db.get(QuotaReservation, reservation_id)
    if r is None:
        raise HTTPException(404, "占用记录不存在")
    quota_svc.release(db, r)
    db.commit()
    return reservation_dict(r)


@router.post("/usage")
def report_usage(
    payload: UsageReportIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN", "PI", "ANALYST")),
):
    """上报用量消耗。同一 idempotency_key 重复上报只扣减一次，
    返回原回执并标记 duplicate；每次上报均留痕可查。"""
    try:
        event, duplicated = quota_svc.report_usage(
            db, payload.project_id, payload.kind, payload.amount,
            payload.idempotency_key, note=payload.note,
        )
    except QuotaError as exc:
        raise HTTPException(409, str(exc))
    db.commit()
    return {
        "event": usage_event_dict(event),
        "duplicate": duplicated,
        "message": "重复上报：额度未重复扣减，已登记重复回执" if duplicated else "扣减成功",
    }


@router.get("/usage")
def list_usage(
    project_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    q = db.query(UsageEvent).join(QuotaAccount, UsageEvent.account_id == QuotaAccount.id)
    if project_id:
        q = q.filter(QuotaAccount.project_id == project_id)
    events = q.order_by(UsageEvent.id.desc()).limit(100).all()
    return [usage_event_dict(e) for e in events]


@router.get("/usage/by-key/{idempotency_key}/receipts")
def usage_receipts(
    idempotency_key: str,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """按幂等键查询回执：返回用量事件与全部上报记录（含重复回执）。"""
    event = db.query(UsageEvent).filter(UsageEvent.idempotency_key == idempotency_key).first()
    if event is None:
        raise HTTPException(404, "该幂等键无对应用量事件")
    reports = (
        db.query(UsageReport)
        .filter(UsageReport.event_id == event.id)
        .order_by(UsageReport.id)
        .all()
    )
    return {
        "event": usage_event_dict(event),
        "reports": [usage_report_dict(r) for r in reports],
        "deducted_once": True,
    }
