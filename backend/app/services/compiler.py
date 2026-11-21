"""资格编译器：将产品字段、用途条件、成员范围与伦理约束求交，
生成按（项目 × 产品 × 用途）隔离的字段投影与有效期。

求交原则：
- 敏感等级上限 = min(伦理批件上限, 用途条件上限)
- 禁用标签 = 伦理禁用 ∪ 用途禁用
- 字段有效窗口 = 字段可用期 ∩ 资格有效期（伦理有效期 ∩ 课题期限）
- 成员范围 = 签发时在职且在任期内的成员
- 资格有效期 = min(伦理有效期止, 课题结题日)；伦理失效则不得签发
任何情况下不对多个用途取并集——每条资格实例只绑定一个用途。
"""
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from ..models import DataProduct, EthicsApproval, Project, ProjectPurpose


class CompileError(Exception):
    """资格编译失败（伦理失效、用途未申报、无在职成员等）。"""


@dataclass
class CompiledQualification:
    field_projection: list[dict]
    covered_member_ids: list[int]
    basis: dict
    valid_from: date
    valid_to: date
    catalog_version: int
    excluded: list[dict] = field(default_factory=list)


def _ethics_snapshot(e: EthicsApproval) -> dict:
    return {
        "approval_no": e.approval_no,
        "scope_subjects": e.scope_subjects,
        "allowed_purposes": e.allowed_purposes,
        "max_sensitivity_level": e.max_sensitivity_level,
        "forbidden_tags": e.forbidden_tags,
        "valid_from": e.valid_from.isoformat(),
        "valid_to": e.valid_to.isoformat(),
        "status": e.status,
    }


def compile_qualification(
    db: Session,
    project: Project,
    product: DataProduct,
    purpose_code: str,
    today: date,
) -> CompiledQualification:
    """对（课题, 产品, 用途）求交。任何约束不满足即抛 CompileError，调用方不得签发。"""
    if project.status != "在研":
        raise CompileError(f"课题状态为「{project.status}」，不在研，不能开通")
    if not (project.start_date <= today <= project.end_date):
        raise CompileError(f"当前日期不在课题期限 {project.start_date}~{project.end_date} 内")
    if product.status != "上架":
        raise CompileError(f"产品「{product.name}」已下架")

    purpose: ProjectPurpose | None = next(
        (p for p in project.purposes if p.purpose_code == purpose_code), None
    )
    if purpose is None:
        raise CompileError(f"用途 {purpose_code} 未在课题「{project.name}」申报")

    # 伦理约束：每次编译实时重查批件状态（批次处理中失效应立即反映）
    approvals = (
        db.query(EthicsApproval)
        .filter(EthicsApproval.project_id == project.id)
        .order_by(EthicsApproval.id)
        .all()
    )
    covering = [
        e for e in approvals
        if e.status == "有效"
        and e.valid_from <= today <= e.valid_to
        and ("*" in e.allowed_purposes or purpose_code in e.allowed_purposes)
    ]
    if not covering:
        invalid = [
            f"{e.approval_no}(状态:{e.status}, 有效期:{e.valid_from}~{e.valid_to})"
            for e in approvals
        ]
        detail = "；".join(invalid) if invalid else "课题无任何伦理批件"
        raise CompileError(f"无覆盖用途 {purpose_code} 的有效伦理批件：{detail}")

    # 多份批件同时覆盖时取交集：等级取下限，禁用标签取并集，有效期取下限
    ethics_max = min(e.max_sensitivity_level for e in covering)
    ethics_forbidden = sorted({t for e in covering for t in e.forbidden_tags})
    ethics_valid_to = min(e.valid_to for e in covering)

    effective_max = min(ethics_max, purpose.max_sensitivity_level)
    forbidden = sorted(set(ethics_forbidden) | set(purpose.forbidden_tags))

    valid_from = today
    valid_to = min(ethics_valid_to, project.end_date)
    if valid_to < valid_from:
        raise CompileError(f"求交后有效期为空（伦理/课题期限截止 {valid_to} 早于今日）")

    # 成员范围：签发时在职且在任期内
    covered = [
        m for m in project.members
        if m.status == "在职" and m.valid_from <= today <= m.valid_to
    ]
    if not covered:
        raise CompileError("课题当前无在职成员，资格无可用主体")

    # 字段求交
    projection: list[dict] = []
    excluded: list[dict] = []
    for f in product.fields:
        if not f.is_active:
            excluded.append({"field_name": f.field_name, "reason": "字段已停用"})
            continue
        if f.sensitivity_level > effective_max:
            excluded.append({
                "field_name": f.field_name,
                "reason": f"敏感等级 L{f.sensitivity_level} 超过求交上限 L{effective_max}",
            })
            continue
        hit = sorted(set(f.tags) & set(forbidden))
        if hit:
            excluded.append({
                "field_name": f.field_name,
                "reason": f"命中禁用标签：{'、'.join(hit)}",
            })
            continue
        win_from = max(f.available_from, valid_from)
        win_to = min(f.available_to, valid_to)
        if win_from > win_to:
            excluded.append({
                "field_name": f.field_name,
                "reason": f"字段可用期 {f.available_from}~{f.available_to} 与资格有效期无交集",
            })
            continue
        projection.append({
            "field_name": f.field_name,
            "semantic": f.semantic,
            "data_type": f.data_type,
            "sensitivity_level": f.sensitivity_level,
            "tags": f.tags,
            "window_from": win_from.isoformat(),
            "window_to": win_to.isoformat(),
        })

    if not projection:
        raise CompileError("求交后可用字段为空，不能签发空投影资格")

    basis = {
        "compiled_at": today.isoformat(),
        "project": {"code": project.code, "name": project.name, "end_date": project.end_date.isoformat()},
        "purpose": {
            "purpose_code": purpose.purpose_code,
            "description": purpose.description,
            "max_sensitivity_level": purpose.max_sensitivity_level,
            "forbidden_tags": purpose.forbidden_tags,
            "export_allowed": purpose.export_allowed,
        },
        "ethics": [_ethics_snapshot(e) for e in covering],
        "effective_max_sensitivity": effective_max,
        "effective_forbidden_tags": forbidden,
        "covered_members": [
            {"id": m.id, "name": m.name, "role": m.role,
             "valid_from": m.valid_from.isoformat(), "valid_to": m.valid_to.isoformat()}
            for m in covered
        ],
        "excluded_fields": excluded,
        "rule": "敏感等级=min(伦理,用途)；禁用标签=伦理∪用途；窗口=字段可用期∩资格有效期；不对多用途取并集",
    }
    return CompiledQualification(
        field_projection=projection,
        covered_member_ids=[m.id for m in covered],
        basis=basis,
        valid_from=valid_from,
        valid_to=valid_to,
        catalog_version=product.catalog_version,
        excluded=excluded,
    )
