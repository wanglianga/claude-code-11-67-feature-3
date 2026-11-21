"""产品目录路由：浏览目录、管理字段（变更留痕并递增目录版本）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CatalogChangeLog, DataProduct, ProductField, User
from ..schemas import FieldUpdateIn
from ..security import current_user, require_roles
from ..serializers import product_dict

router = APIRouter(prefix="/api/catalog", tags=["产品目录"])


@router.get("/products")
def list_products(db: Session = Depends(get_db), _: User = Depends(current_user)):
    products = db.query(DataProduct).order_by(DataProduct.id).all()
    return [product_dict(p) for p in products]


@router.get("/products/{product_id}")
def product_detail(product_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    product = db.get(DataProduct, product_id)
    if product is None:
        raise HTTPException(404, "产品不存在")
    return product_dict(product, with_fields=True)


@router.put("/products/{product_id}/fields/{field_id}")
def update_field(
    product_id: int,
    field_id: int,
    payload: FieldUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("ADMIN")),
):
    """修改字段定义：记录变更日志并递增目录版本（既有资格实例的投影快照不受影响）。"""
    product = db.get(DataProduct, product_id)
    field = db.get(ProductField, field_id)
    if product is None or field is None or field.product_id != product.id:
        raise HTTPException(404, "产品或字段不存在")

    changes: dict = {}
    if payload.sensitivity_level is not None and payload.sensitivity_level != field.sensitivity_level:
        changes["sensitivity_level"] = {"old": field.sensitivity_level, "new": payload.sensitivity_level}
        field.sensitivity_level = payload.sensitivity_level
    if payload.tags is not None and payload.tags != field.tags:
        changes["tags"] = {"old": field.tags, "new": payload.tags}
        field.tags = payload.tags
    if payload.semantic is not None and payload.semantic != field.semantic:
        changes["semantic"] = {"old": field.semantic, "new": payload.semantic}
        field.semantic = payload.semantic
    if payload.available_from is not None:
        v = datetime.strptime(payload.available_from, "%Y-%m-%d").date()
        if v != field.available_from:
            changes["available_from"] = {"old": field.available_from.isoformat(), "new": v.isoformat()}
            field.available_from = v
    if payload.available_to is not None:
        v = datetime.strptime(payload.available_to, "%Y-%m-%d").date()
        if v != field.available_to:
            changes["available_to"] = {"old": field.available_to.isoformat(), "new": v.isoformat()}
            field.available_to = v
    if payload.is_active is not None and payload.is_active != field.is_active:
        changes["is_active"] = {"old": field.is_active, "new": payload.is_active}
        field.is_active = payload.is_active

    if not changes:
        return product_dict(product, with_fields=True)

    product.catalog_version += 1
    db.add(CatalogChangeLog(
        product_id=product.id, change_type="修改字段",
        detail={"field_name": field.field_name, "changes": changes,
                "catalog_version": product.catalog_version},
        actor=user.username,
    ))
    db.commit()
    return product_dict(product, with_fields=True)


@router.get("/products/{product_id}/changes")
def product_changes(product_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    logs = (
        db.query(CatalogChangeLog)
        .filter(CatalogChangeLog.product_id == product_id)
        .order_by(CatalogChangeLog.id.desc())
        .limit(100)
        .all()
    )
    return [
        {"id": x.id, "change_type": x.change_type, "detail": x.detail,
         "actor": x.actor, "created_at": x.created_at.isoformat()}
        for x in logs
    ]
