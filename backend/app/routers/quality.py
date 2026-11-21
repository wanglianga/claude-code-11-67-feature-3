"""数据产品批次质量认证路由。

- 批次清单固定中心、产品分区、字段字典版本与统计时间窗；源记录只增不改（无更新/删除端点）。
- 写操作（入库批次、维护契约规则、重认证、重建基线）仅 ADMIN；查询对所有登录角色开放。
- 批次更正 = 新建更正批次并认证（源记录原样保留）；规则调整 = 规则升版本后重认证，
  两种情况都生成新的认证版本，旧认证完整保留。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    BatchRecord, DataBatch, DataProduct, DistributionBaseline, ProductField,
    QualityCertification, QualityRule, User,
)
from ..schemas import DataBatchIn, RecertifyIn, RuleAdjustIn, RuleUpsertIn
from ..security import current_user, require_roles
from ..serializers import (
    baseline_dict, certification_dict, data_batch_dict, rule_dict,
)
from ..services.quality import QualityError, certify_batch, new_batch_no, rebuild_baseline

router = APIRouter(prefix="/api/quality", tags=["批次质量认证"])


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(400, f"日期格式非法：{s}（应为 YYYY-MM-DD）")


# ----------------------------- 数据批次 -----------------------------

@router.post("/batches")
def create_batch(
    payload: DataBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    """批次入库（源记录原样留存）并可立即认证；批次清单固定四要素。"""
    product = db.get(DataProduct, payload.product_id)
    if product is None:
        raise HTTPException(400, f"产品 id={payload.product_id} 不存在")
    window_from = _parse_date(payload.window_from)
    window_to = _parse_date(payload.window_to)
    if window_from > window_to:
        raise HTTPException(400, "统计时间窗起晚于止")
    if not payload.records:
        raise HTTPException(400, "批次至少包含一条源记录")

    keys = [r.record_key for r in payload.records]
    if len(keys) != len(set(keys)):
        raise HTTPException(400, "批次内 record_key 必须唯一")

    batch = DataBatch(
        batch_no=new_batch_no(), product_id=product.id,
        center_code=payload.center_code, partition_name=payload.partition_name,
        dict_version=payload.dict_version, window_from=window_from,
        window_to=window_to, note=payload.note, created_by=user.username,
    )
    db.add(batch)
    db.flush()
    for r in payload.records:
        # 源记录原样落库：payload 不做任何规范化或改写
        db.add(BatchRecord(batch_id=batch.id, record_key=r.record_key, payload=r.payload))
    db.flush()

    cert = None
    if payload.certify:
        cert = certify_batch(db, batch, payload.trigger, user.username)
    db.commit()
    return {"batch": data_batch_dict(batch, with_counts=True),
            "certification": certification_dict(cert, detail=True) if cert else None}


@router.get("/batches")
def list_batches(
    product_id: int | None = None,
    partition_name: str | None = None,
    dict_version: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    q = db.query(DataBatch).order_by(DataBatch.id.desc())
    if product_id:
        q = q.filter(DataBatch.product_id == product_id)
    if partition_name:
        q = q.filter(DataBatch.partition_name == partition_name)
    if dict_version:
        q = q.filter(DataBatch.dict_version == dict_version)
    return [data_batch_dict(b, with_counts=True) for b in q.limit(200).all()]


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: int, db: Session = Depends(get_db),
                 _: User = Depends(current_user)):
    batch = db.get(DataBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    return data_batch_dict(batch, with_counts=True)


@router.get("/batches/{batch_id}/records")
def batch_records(
    batch_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    """源记录查询（只读）：证据样本凭 record_key 回溯到原始记录。"""
    batch = db.get(DataBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    limit = min(max(limit, 1), 200)
    rows = batch.records[offset:offset + limit]
    return {
        "batch_id": batch.id, "total": len(batch.records), "limit": limit,
        "offset": offset,
        "records": [{"id": r.id, "record_key": r.record_key, "payload": r.payload,
                     "created_at": r.created_at.isoformat()} for r in rows],
    }


@router.get("/batches/{batch_id}/records/by-key/{record_key}")
def batch_record_by_key(batch_id: int, record_key: str, db: Session = Depends(get_db),
                        _: User = Depends(current_user)):
    batch = db.get(DataBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    rec = (
        db.query(BatchRecord)
        .filter(BatchRecord.batch_id == batch_id, BatchRecord.record_key == record_key)
        .first()
    )
    if rec is None:
        raise HTTPException(404, "源记录不存在")
    return {"id": rec.id, "record_key": rec.record_key, "payload": rec.payload,
            "created_at": rec.created_at.isoformat()}


@router.post("/batches/{batch_id}/correction")
def correct_batch(
    batch_id: int,
    payload: DataBatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    """批次更正：以更正后的源记录新建批次并认证，旧批次、旧记录与旧认证全部保留。"""
    original = db.get(DataBatch, batch_id)
    if original is None:
        raise HTTPException(404, "原批次不存在")
    payload.trigger = "批次更正"  # 更正批次固定触发标记，认证版本据此留痕
    created = create_batch(payload, db, user)
    # 在新批次备注中保留可追溯链路
    new_batch = db.get(DataBatch, created["batch"]["id"])
    tail = f"；{payload.note}" if payload.note else ""
    new_batch.note = f"更正批次（原批次 {original.batch_no}）{tail}"
    db.commit()
    created["batch"] = data_batch_dict(new_batch, with_counts=True)
    return created


@router.post("/batches/{batch_id}/recertify")
def recertify(
    batch_id: int,
    payload: RecertifyIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    """规则调整后重认证：生成新认证版本，旧版本保留；源记录不发生任何变化。"""
    batch = db.get(DataBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "批次不存在")
    try:
        cert = certify_batch(db, batch, payload.trigger, user.username, payload.note)
    except QualityError as exc:
        raise HTTPException(400, str(exc))
    db.commit()
    return certification_dict(cert, detail=True)


# ----------------------------- 认证版本与字段结果 -----------------------------

@router.get("/certifications")
def list_certifications(
    batch_id: int | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    q = db.query(QualityCertification).order_by(
        QualityCertification.batch_id.desc(), QualityCertification.version.desc())
    if batch_id:
        q = q.filter(QualityCertification.batch_id == batch_id)
    return [certification_dict(c) for c in q.limit(200).all()]


@router.get("/certifications/{cert_id}")
def certification_detail(cert_id: int, db: Session = Depends(get_db),
                         _: User = Depends(current_user)):
    cert = db.get(QualityCertification, cert_id)
    if cert is None:
        raise HTTPException(404, "认证版本不存在")
    return certification_dict(cert, detail=True)


# ----------------------------- 硬性数据契约规则 -----------------------------

@router.get("/rules")
def list_rules(product_id: int | None = None, db: Session = Depends(get_db),
               _: User = Depends(current_user)):
    q = db.query(QualityRule).order_by(QualityRule.product_id, QualityRule.id)
    if product_id:
        q = q.filter(QualityRule.product_id == product_id)
    return [rule_dict(r) for r in q.all()]


@router.post("/rules")
def upsert_rule(
    payload: RuleUpsertIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    """按（产品 × 字段 × 规则类型）维护契约规则；同型规则已存在则更新参数（不升版本）。

    字段风险等级用于组合评级：高风险字段漂移/阻断失败不得被总体通过率稀释。
    """
    if payload.rule_type not in ("missing", "invalid", "uniqueness", "consistency"):
        raise HTTPException(400, "rule_type 仅支持 missing/invalid/uniqueness/consistency")
    if payload.risk_level not in ("高", "中", "低"):
        raise HTTPException(400, "risk_level 仅支持 高/中/低")
    product = db.get(DataProduct, payload.product_id)
    if product is None:
        raise HTTPException(400, f"产品 id={payload.product_id} 不存在")
    field = (
        db.query(ProductField)
        .filter(ProductField.product_id == product.id,
                ProductField.field_name == payload.field_name)
        .first()
    )
    if field is None:
        raise HTTPException(400, f"字段 {payload.field_name} 不在产品 {product.code} 字典中")

    # 同（产品×字段×规则类型×字典版本）视为同一条规则：通用规则与版本专属规则互不覆盖
    version_cond = (QualityRule.dict_version.is_(None)
                    if payload.dict_version is None
                    else QualityRule.dict_version == payload.dict_version)
    rule = (
        db.query(QualityRule)
        .filter(QualityRule.product_id == product.id,
                QualityRule.field_name == payload.field_name,
                QualityRule.rule_type == payload.rule_type,
                version_cond)
        .first()
    )
    if rule is None:
        rule = QualityRule(product_id=product.id, field_name=payload.field_name,
                           rule_type=payload.rule_type, rule_version=1,
                           dict_version=payload.dict_version)
        db.add(rule)
    rule.params = payload.params
    rule.blocking = payload.blocking
    rule.risk_level = payload.risk_level
    rule.dict_version = payload.dict_version
    rule.note = payload.note
    rule.updated_by = user.username
    rule.updated_at = datetime.utcnow()
    db.flush()
    db.commit()
    return rule_dict(rule)


@router.post("/rules/{rule_id}/adjust")
def adjust_rule(
    rule_id: int,
    payload: RuleAdjustIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    """规则调整：修改契约并递增规则版本；已产生的认证仍引用旧版本，需重认证才生效。"""
    rule = db.get(QualityRule, rule_id)
    if rule is None:
        raise HTTPException(404, "规则不存在")
    if payload.params is not None:
        rule.params = payload.params
    if payload.blocking is not None:
        rule.blocking = payload.blocking
    if payload.risk_level is not None:
        if payload.risk_level not in ("高", "中", "低"):
            raise HTTPException(400, "risk_level 仅支持 高/中/低")
        rule.risk_level = payload.risk_level
    if payload.enabled is not None:
        rule.enabled = payload.enabled
    if payload.note is not None:
        rule.note = payload.note
    rule.rule_version += 1
    rule.updated_by = user.username
    rule.updated_at = datetime.utcnow()
    db.commit()
    return rule_dict(rule)


# ----------------------------- 分布基线 -----------------------------

@router.get("/baselines")
def list_baselines(
    product_id: int | None = None,
    partition_name: str | None = None,
    field_name: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(current_user),
):
    q = db.query(DistributionBaseline).order_by(DistributionBaseline.id)
    if product_id:
        q = q.filter(DistributionBaseline.product_id == product_id)
    if partition_name:
        q = q.filter(DistributionBaseline.partition_name == partition_name)
    if field_name:
        q = q.filter(DistributionBaseline.field_name == field_name)
    return [baseline_dict(b) for b in q.all()]


@router.post("/baselines/rebuild")
def rebuild(
    product_id: int,
    partition_name: str,
    field_name: str,
    dict_version: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    try:
        bl = rebuild_baseline(db, product_id, partition_name, field_name, dict_version)
    except QualityError as exc:
        raise HTTPException(400, str(exc))
    if bl is None:
        raise HTTPException(400, "该分区/字典版本下无合格历史批次，无法建立基线")
    db.commit()
    return baseline_dict(bl)
