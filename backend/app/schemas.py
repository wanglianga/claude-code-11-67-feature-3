"""请求体模型。"""
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class FieldUpdateIn(BaseModel):
    sensitivity_level: int | None = Field(default=None, ge=1, le=4)
    tags: list[str] | None = None
    available_from: str | None = None  # YYYY-MM-DD
    available_to: str | None = None
    is_active: bool | None = None
    semantic: str | None = None


class BatchItemIn(BaseModel):
    project_id: int
    product_id: int
    purpose_code: str


class BatchCreateIn(BaseModel):
    title: str = ""
    items: list[BatchItemIn]


class RevokeIn(BaseModel):
    reason: str = ""


class AccessQueryIn(BaseModel):
    project_id: int
    product_id: int
    purpose_code: str
    kind: str = "查询"  # 查询/导出
    requested_fields: list[str] = []
    request_id: str  # 客户端请求号：断线重试幂等
    export_rows: int = Field(default=100, ge=1)


class ReservationIn(BaseModel):
    project_id: int
    kind: str = "查询"
    note: str = ""


class UsageReportIn(BaseModel):
    project_id: int
    kind: str = "机时"  # 查询/导出/机时
    amount: float = 1
    idempotency_key: str
    note: str = ""


# ---------------- 批次质量认证 ----------------

class BatchRecordIn(BaseModel):
    record_key: str
    payload: dict  # 源记录原样提交，后端不改写


class DataBatchIn(BaseModel):
    product_id: int
    center_code: str
    partition_name: str
    dict_version: str
    window_from: str  # YYYY-MM-DD
    window_to: str
    note: str = ""
    records: list[BatchRecordIn]
    certify: bool = True          # 入库后立即按当前规则认证
    trigger: str = "首次认证"


class RuleUpsertIn(BaseModel):
    product_id: int
    field_name: str
    rule_type: str  # missing/invalid/uniqueness/consistency
    params: dict = {}
    blocking: bool = True
    risk_level: str = "中"  # 高/中/低
    dict_version: str | None = None  # NULL=与版本无关的通用规则
    note: str = ""


class RuleAdjustIn(BaseModel):
    """规则调整：修改参数并升规则版本，后续重认证生成新版本，旧认证保留。"""
    params: dict | None = None
    blocking: bool | None = None
    risk_level: str | None = None
    enabled: bool | None = None
    note: str | None = None


class RecertifyIn(BaseModel):
    trigger: str = "规则调整"  # 批次更正/规则调整
    note: str = ""
