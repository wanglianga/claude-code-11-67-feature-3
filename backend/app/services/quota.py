"""额度账本服务：并发占用（行级锁保证）、幂等扣减、重复回执可查。"""
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import QuotaAccount, QuotaReservation, UsageEvent, UsageReport


class QuotaError(Exception):
    """额度不足或并发占用超限。"""


def get_account(db: Session, project_id: int) -> QuotaAccount:
    account = db.query(QuotaAccount).filter(QuotaAccount.project_id == project_id).first()
    if account is None:
        raise QuotaError("该课题未建立额度账户")
    return account


def lock_account(db: Session, project_id: int) -> QuotaAccount:
    """SELECT ... FOR UPDATE：占用/扣减必须在账户行锁内串行化。"""
    account = (
        db.query(QuotaAccount)
        .filter(QuotaAccount.project_id == project_id)
        .with_for_update()
        .first()
    )
    if account is None:
        raise QuotaError("该课题未建立额度账户")
    return account


def active_reservations(db: Session, account_id: int) -> int:
    return (
        db.query(QuotaReservation)
        .filter(QuotaReservation.account_id == account_id, QuotaReservation.status == "占用中")
        .count()
    )


def acquire(db: Session, project_id: int, kind: str, note: str = "") -> QuotaReservation:
    """占用一个并发槽。占用数达到上限即拒绝。"""
    account = lock_account(db, project_id)
    if active_reservations(db, account.id) >= account.max_concurrent:
        raise QuotaError(f"并发占用已达上限 {account.max_concurrent}，请稍后重试")
    reservation = QuotaReservation(account_id=account.id, kind=kind, note=note)
    db.add(reservation)
    db.flush()
    return reservation


def release(db: Session, reservation: QuotaReservation, status: str = "已释放") -> None:
    if reservation.status != "占用中":
        return
    reservation.status = status
    reservation.released_at = datetime.utcnow()


def _balance_snapshot(account: QuotaAccount) -> dict:
    return {
        "used_query": account.used_query, "budget_query": account.budget_query,
        "used_export_rows": account.used_export_rows, "budget_export_rows": account.budget_export_rows,
        "used_compute_hours": account.used_compute_hours, "budget_compute_hours": account.budget_compute_hours,
    }


def _apply_consumption(account: QuotaAccount, kind: str, amount: float) -> None:
    if kind == "查询":
        if account.used_query + amount > account.budget_query:
            raise QuotaError(f"查询额度不足：已用 {account.used_query}/{account.budget_query}")
        account.used_query += int(amount)
    elif kind == "导出":
        if account.used_export_rows + amount > account.budget_export_rows:
            raise QuotaError(f"导出行数额度不足：已用 {account.used_export_rows}/{account.budget_export_rows}")
        account.used_export_rows += int(amount)
    elif kind == "机时":
        if account.used_compute_hours + amount > account.budget_compute_hours:
            raise QuotaError(f"机时额度不足：已用 {account.used_compute_hours}/{account.budget_compute_hours}")
        account.used_compute_hours += amount
    else:
        raise QuotaError(f"未知用量类型：{kind}")


def report_usage(
    db: Session,
    project_id: int,
    kind: str,
    amount: float,
    idempotency_key: str,
    access_event_id: int | None = None,
    note: str = "",
) -> tuple[UsageEvent, bool]:
    """上报一次用量消耗。幂等：同一 idempotency_key 重复上报只扣减一次，
    第二次起返回原回执并登记一条重复上报记录（重复回执可查）。
    返回 (用量事件, 是否重复上报)。
    """
    existing = (
        db.query(UsageEvent)
        .filter(UsageEvent.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        db.add(UsageReport(event_id=existing.id, is_duplicate=True,
                           note=note or "断线重试/重复上报，未重复扣减"))
        db.flush()
        return existing, True

    account = lock_account(db, project_id)
    _apply_consumption(account, kind, amount)
    event = UsageEvent(
        account_id=account.id,
        kind=kind,
        amount=amount,
        idempotency_key=idempotency_key,
        receipt_no="RC" + uuid.uuid4().hex[:18].upper(),
        access_event_id=access_event_id,
        balance_after=_balance_snapshot(account),
    )
    db.add(event)
    db.flush()
    db.add(UsageReport(event_id=event.id, is_duplicate=False, note=note or "首次上报"))
    db.flush()
    return event, False
