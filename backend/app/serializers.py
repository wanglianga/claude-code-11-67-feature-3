"""ORM → 字典序列化（接口出参统一在此组装）。"""
from .models import (
    AccessEvent, DataBatch, DataProduct, DistributionBaseline, EthicsApproval,
    FieldQualityResult, ProductField, Project, ProjectMember, ProjectPurpose,
    QualificationBatch, QualificationInstance, QualityCertification, QualityRule,
    QuotaAccount, QuotaReservation, UsageEvent, UsageReport, User,
)


def user_dict(u: User) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "role": u.role, "member_name": u.member_name}


def field_dict(f: ProductField) -> dict:
    return {
        "id": f.id, "field_name": f.field_name, "semantic": f.semantic,
        "data_type": f.data_type, "sensitivity_level": f.sensitivity_level,
        "tags": f.tags, "available_from": f.available_from.isoformat(),
        "available_to": f.available_to.isoformat(), "is_active": f.is_active,
    }


def product_dict(p: DataProduct, with_fields: bool = False) -> dict:
    d = {
        "id": p.id, "code": p.code, "name": p.name,
        "source_system": p.source_system, "update_frequency": p.update_frequency,
        "owner_dept": p.owner_dept, "description": p.description,
        "status": p.status, "catalog_version": p.catalog_version,
        "field_count": len(p.fields),
    }
    if with_fields:
        d["fields"] = [field_dict(f) for f in p.fields]
    return d


def purpose_dict(p: ProjectPurpose) -> dict:
    return {
        "id": p.id, "purpose_code": p.purpose_code, "description": p.description,
        "max_sensitivity_level": p.max_sensitivity_level,
        "forbidden_tags": p.forbidden_tags, "export_allowed": p.export_allowed,
    }


def member_dict(m: ProjectMember) -> dict:
    return {
        "id": m.id, "name": m.name, "role": m.role,
        "valid_from": m.valid_from.isoformat(), "valid_to": m.valid_to.isoformat(),
        "status": m.status,
    }


def ethics_dict(e: EthicsApproval) -> dict:
    return {
        "id": e.id, "approval_no": e.approval_no, "scope_subjects": e.scope_subjects,
        "allowed_purposes": e.allowed_purposes,
        "max_sensitivity_level": e.max_sensitivity_level,
        "forbidden_tags": e.forbidden_tags,
        "valid_from": e.valid_from.isoformat(), "valid_to": e.valid_to.isoformat(),
        "status": e.status,
    }


def project_dict(p: Project, detail: bool = False) -> dict:
    d = {
        "id": p.id, "code": p.code, "name": p.name, "pi_name": p.pi_name,
        "status": p.status, "start_date": p.start_date.isoformat(),
        "end_date": p.end_date.isoformat(),
    }
    if detail:
        d["purposes"] = [purpose_dict(x) for x in p.purposes]
        d["members"] = [member_dict(x) for x in p.members]
        d["ethics"] = [ethics_dict(x) for x in p.ethics]
    return d


def qualification_dict(q: QualificationInstance, detail: bool = False) -> dict:
    d = {
        "id": q.id, "batch_id": q.batch_id,
        "project_id": q.project_id, "project_code": q.project.code if q.project else None,
        "project_name": q.project.name if q.project else None,
        "product_id": q.product_id, "product_code": q.product.code if q.product else None,
        "product_name": q.product.name if q.product else None,
        "purpose_code": q.purpose_code, "status": q.status,
        "fail_reason": q.fail_reason,
        "valid_from": q.valid_from.isoformat() if q.valid_from else None,
        "valid_to": q.valid_to.isoformat() if q.valid_to else None,
        "version": q.version, "issued_at": q.issued_at.isoformat() if q.issued_at else None,
        "issued_by": q.issued_by,
        "revoked_at": q.revoked_at.isoformat() if q.revoked_at else None,
        "revoke_reason": q.revoke_reason,
        "field_count": len(q.field_projection or []),
        "catalog_version": q.catalog_version,
    }
    if detail:
        d["field_projection"] = q.field_projection
        d["covered_member_ids"] = q.covered_member_ids
        d["basis"] = q.basis
    return d


def batch_dict(b: QualificationBatch, with_items: bool = False) -> dict:
    d = {
        "id": b.id, "batch_no": b.batch_no, "title": b.title, "status": b.status,
        "total": b.total, "succeeded": b.succeeded, "failed": b.failed,
        "created_by": b.created_by, "created_at": b.created_at.isoformat(),
        "finished_at": b.finished_at.isoformat() if b.finished_at else None,
    }
    if with_items:
        d["items"] = [qualification_dict(q) for q in b.items]
    return d


def account_dict(a: QuotaAccount, active: int = 0) -> dict:
    return {
        "id": a.id, "project_id": a.project_id,
        "project_code": a.project.code if a.project else None,
        "project_name": a.project.name if a.project else None,
        "max_concurrent": a.max_concurrent, "active_reservations": active,
        "budget_query": a.budget_query, "used_query": a.used_query,
        "budget_export_rows": a.budget_export_rows, "used_export_rows": a.used_export_rows,
        "budget_compute_hours": a.budget_compute_hours, "used_compute_hours": a.used_compute_hours,
    }


def reservation_dict(r: QuotaReservation) -> dict:
    return {
        "id": r.id, "account_id": r.account_id, "kind": r.kind, "status": r.status,
        "access_event_id": r.access_event_id, "note": r.note,
        "created_at": r.created_at.isoformat(),
        "released_at": r.released_at.isoformat() if r.released_at else None,
    }


def usage_event_dict(e: UsageEvent, with_reports: bool = False) -> dict:
    d = {
        "id": e.id, "account_id": e.account_id, "kind": e.kind, "amount": e.amount,
        "idempotency_key": e.idempotency_key, "receipt_no": e.receipt_no,
        "access_event_id": e.access_event_id,
        "balance_after": e.balance_after, "created_at": e.created_at.isoformat(),
    }
    if with_reports:
        d["reports"] = [usage_report_dict(r) for r in e.reports]
    return d


def usage_report_dict(r: UsageReport) -> dict:
    return {
        "id": r.id, "event_id": r.event_id, "is_duplicate": r.is_duplicate,
        "note": r.note, "reported_at": r.reported_at.isoformat(),
    }


def access_event_dict(e: AccessEvent, detail: bool = False) -> dict:
    d = {
        "id": e.id, "request_id": e.request_id,
        "project_id": e.project_id, "product_id": e.product_id,
        "purpose_code": e.purpose_code,
        "member_id": e.member_id, "member_name": e.member_name,
        "qualification_id": e.qualification_id,
        "kind": e.kind, "status": e.status, "deny_reason": e.deny_reason,
        "requested_fields": e.requested_fields, "granted_fields": e.granted_fields,
        "created_at": e.created_at.isoformat(),
    }
    if detail:
        d["product_snapshot"] = e.product_snapshot
        d["qualification_snapshot"] = e.qualification_snapshot
        d["quota_snapshot"] = e.quota_snapshot
    return d


# ---------------- 批次质量认证 ----------------

def data_batch_dict(b: DataBatch, with_counts: bool = False) -> dict:
    d = {
        "id": b.id, "batch_no": b.batch_no, "product_id": b.product_id,
        "product_code": b.product.code if b.product else None,
        "product_name": b.product.name if b.product else None,
        "center_code": b.center_code, "partition_name": b.partition_name,
        "dict_version": b.dict_version,
        "window_from": b.window_from.isoformat(),
        "window_to": b.window_to.isoformat(),
        "status": b.status, "note": b.note,
        "created_by": b.created_by, "created_at": b.created_at.isoformat(),
    }
    if with_counts:
        latest = b.certifications[0] if b.certifications else None
        d["record_count"] = len(b.records)
        d["latest_decision"] = latest.decision if latest else None
        d["latest_version"] = latest.version if latest else None
        d["latest_pass_rate"] = latest.pass_rate if latest else None
        d["cert_versions"] = [
            {"id": c.id, "version": c.version, "decision": c.decision,
             "rule_version": c.rule_version, "trigger": c.trigger,
             "created_at": c.created_at.isoformat()}
            for c in b.certifications
        ]
    return d


def rule_dict(r: QualityRule) -> dict:
    return {
        "id": r.id, "product_id": r.product_id, "field_name": r.field_name,
        "dict_version": r.dict_version, "rule_type": r.rule_type, "params": r.params,
        "blocking": r.blocking, "risk_level": r.risk_level,
        "rule_version": r.rule_version, "enabled": r.enabled, "note": r.note,
        "updated_by": r.updated_by, "updated_at": r.updated_at.isoformat(),
    }


def baseline_dict(bl: DistributionBaseline) -> dict:
    return {
        "id": bl.id, "product_id": bl.product_id, "partition_name": bl.partition_name,
        "field_name": bl.field_name, "dict_version": bl.dict_version,
        "sample_size": bl.sample_size, "stats_kind": bl.stats.get("kind"),
        "stats": bl.stats, "seasonal_stats": bl.seasonal_stats,
        "source_batch_ids": bl.source_batch_ids,
        "min_stable_sample": bl.min_stable_sample,
        "rebuilt_at": bl.rebuilt_at.isoformat(),
    }


def field_result_dict(r: FieldQualityResult, with_evidence=False) -> dict:
    d = {
        "id": r.id, "certification_id": r.certification_id,
        "field_name": r.field_name, "partition_name": r.partition_name,
        "dict_version": r.dict_version, "sample_size": r.sample_size,
        "fitness_grade": r.fitness_grade, "contract_passed": r.contract_passed,
        "drift_status": r.drift_status, "metrics": r.metrics,
        "drift_detail": r.drift_detail, "block_reasons": r.block_reasons,
        "rule_refs": r.rule_refs,
    }
    if with_evidence:
        d["evidence_samples"] = r.evidence_samples
    return d


def certification_dict(c: QualityCertification, detail=False) -> dict:
    d = {
        "id": c.id, "batch_id": c.batch_id, "version": c.version,
        "rule_version": c.rule_version, "decision": c.decision,
        "pass_rate": c.pass_rate, "field_count": c.field_count,
        "passed_fields": c.passed_fields, "blocked_fields": c.blocked_fields,
        "insufficient_fields": c.insufficient_fields,
        "research_fitness": c.research_fitness, "summary": c.summary,
        "trigger": c.trigger, "created_by": c.created_by,
        "created_at": c.created_at.isoformat(),
    }
    if detail:
        d["batch"] = data_batch_dict(c.batch)
        d["field_results"] = [field_result_dict(r, with_evidence=True)
                              for r in c.field_results]
    return d
