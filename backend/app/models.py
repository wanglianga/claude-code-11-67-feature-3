"""数据模型：产品目录、课题档案、资格实例、额度账本、访问事件与审计快照。"""
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# 敏感等级：1 公开 / 2 内部 / 3 敏感 / 4 高度敏感（直接标识、遗传信息等）
SENSITIVITY_LABELS = {1: "L1 公开", 2: "L2 内部", 3: "L3 敏感", 4: "L4 高度敏感"}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(sa.String(256))
    display_name: Mapped[str] = mapped_column(sa.String(64))
    # ADMIN 数据治理管理员 / PI 课题负责人 / ANALYST 数据分析师 / AUDITOR 审计员
    role: Mapped[str] = mapped_column(sa.String(16))
    # 分析师/PI 登录后在各课题中对应的成员姓名（成员记录按课题分别建档）
    member_name: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


class DataProduct(Base):
    __tablename__ = "data_products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(128))
    source_system: Mapped[str] = mapped_column(sa.String(64))   # 来源系统：PACS/LIS/随访平台/样本库
    update_frequency: Mapped[str] = mapped_column(sa.String(32))  # 更新频率：每日/每周/每月
    owner_dept: Mapped[str] = mapped_column(sa.String(64), default="")
    description: Mapped[str] = mapped_column(sa.Text, default="")
    status: Mapped[str] = mapped_column(sa.String(16), default="上架")  # 上架/下架
    catalog_version: Mapped[int] = mapped_column(sa.Integer, default=1)  # 目录版本，字段变更即递增
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    fields: Mapped[list["ProductField"]] = relationship(
        back_populates="product", order_by="ProductField.id", cascade="all, delete-orphan"
    )


class ProductField(Base):
    __tablename__ = "product_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    field_name: Mapped[str] = mapped_column(sa.String(64))
    semantic: Mapped[str] = mapped_column(sa.String(256))       # 字段语义（业务含义）
    data_type: Mapped[str] = mapped_column(sa.String(32), default="string")
    sensitivity_level: Mapped[int] = mapped_column(sa.Integer)  # 1-4
    tags: Mapped[list] = mapped_column(JSONB, default=list)     # 直接标识符/准标识符/遗传信息 等
    available_from: Mapped[date] = mapped_column(sa.Date)       # 可用时间范围起
    available_to: Mapped[date] = mapped_column(sa.Date)         # 可用时间范围止
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True)

    product: Mapped[DataProduct] = relationship(back_populates="fields")


class CatalogChangeLog(Base):
    """目录变更日志：字段/产品每次修改留痕，供审计对比"当时定义"。"""

    __tablename__ = "catalog_change_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    change_type: Mapped[str] = mapped_column(sa.String(32))  # 新增字段/修改字段/停用字段/更新产品
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    actor: Mapped[str] = mapped_column(sa.String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(sa.String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(128))
    pi_name: Mapped[str] = mapped_column(sa.String(64))
    status: Mapped[str] = mapped_column(sa.String(16), default="在研")  # 在研/结题/暂停
    start_date: Mapped[date] = mapped_column(sa.Date)
    end_date: Mapped[date] = mapped_column(sa.Date)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    purposes: Mapped[list["ProjectPurpose"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectPurpose.id"
    )
    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectMember.id"
    )
    ethics: Mapped[list["EthicsApproval"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="EthicsApproval.id"
    )


class ProjectPurpose(Base):
    """课题申报的研究目的及其用途条件（字段放行的约束之一）。"""

    __tablename__ = "project_purposes"
    __table_args__ = (sa.UniqueConstraint("project_id", "purpose_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    purpose_code: Mapped[str] = mapped_column(sa.String(32))
    description: Mapped[str] = mapped_column(sa.String(256))
    max_sensitivity_level: Mapped[int] = mapped_column(sa.Integer, default=2)
    forbidden_tags: Mapped[list] = mapped_column(JSONB, default=list)
    export_allowed: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    project: Mapped[Project] = relationship(back_populates="purposes")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (sa.UniqueConstraint("project_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(sa.String(64))
    role: Mapped[str] = mapped_column(sa.String(32))  # PI/数据分析师/研究员/统计师
    valid_from: Mapped[date] = mapped_column(sa.Date)
    valid_to: Mapped[date] = mapped_column(sa.Date)
    status: Mapped[str] = mapped_column(sa.String(16), default="在职")  # 在职/离任

    project: Mapped[Project] = relationship(back_populates="members")


class EthicsApproval(Base):
    """伦理批件：适用对象、允许用途、敏感等级上限与有效期。"""

    __tablename__ = "ethics_approvals"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    approval_no: Mapped[str] = mapped_column(sa.String(64), unique=True)
    scope_subjects: Mapped[str] = mapped_column(sa.String(256))  # 适用对象
    allowed_purposes: Mapped[list] = mapped_column(JSONB, default=list)  # 用途编码列表，["*"] 表示全部
    max_sensitivity_level: Mapped[int] = mapped_column(sa.Integer, default=3)
    forbidden_tags: Mapped[list] = mapped_column(JSONB, default=list)
    valid_from: Mapped[date] = mapped_column(sa.Date)
    valid_to: Mapped[date] = mapped_column(sa.Date)
    status: Mapped[str] = mapped_column(sa.String(16), default="有效")  # 有效/失效/暂停
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    project: Mapped[Project] = relationship(back_populates="ethics")


class QualificationBatch(Base):
    """资格开通批次：一次开通申请的处理结果，逐项独立状态，绝不整体假报成功。"""

    __tablename__ = "qualification_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(sa.String(40), unique=True, index=True)
    title: Mapped[str] = mapped_column(sa.String(128), default="")
    status: Mapped[str] = mapped_column(sa.String(16), default="处理中")  # 完成/部分完成/失败
    total: Mapped[int] = mapped_column(sa.Integer, default=0)
    succeeded: Mapped[int] = mapped_column(sa.Integer, default=0)
    failed: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_by: Mapped[str] = mapped_column(sa.String(64))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)

    items: Mapped[list["QualificationInstance"]] = relationship(back_populates="batch")


class QualificationInstance(Base):
    """资格实例：按（项目 × 产品 × 用途）隔离的字段投影与有效期。

    设计选择：采用独立资格实例模式（每个项目-产品-用途一条记录），
    审计直观、撤回传播范围明确；同一三元组同一时刻至多一条"已签发"。
    """

    __tablename__ = "qualification_instances"
    __table_args__ = (
        sa.Index(
            "uq_active_qualification",
            "project_id", "product_id", "purpose_code",
            unique=True,
            postgresql_where=sa.text("status = '已签发'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int | None] = mapped_column(sa.ForeignKey("qualification_batches.id"), nullable=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    purpose_code: Mapped[str] = mapped_column(sa.String(32))
    status: Mapped[str] = mapped_column(sa.String(16), default="已签发")  # 已签发/签发失败/已撤回
    fail_reason: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    # 字段投影：编译时求交后的可用人字段及各自有效窗口（快照，签发后不再随目录变化）
    field_projection: Mapped[list] = mapped_column(JSONB, default=list)
    covered_member_ids: Mapped[list] = mapped_column(JSONB, default=list)  # 签发时在职成员范围
    # 资格依据：伦理批件快照、用途条件、成员范围、被剔除字段及原因
    basis: Mapped[dict] = mapped_column(JSONB, default=dict)
    catalog_version: Mapped[int] = mapped_column(sa.Integer, default=1)  # 签发依据的目录版本
    valid_from: Mapped[date] = mapped_column(sa.Date)
    valid_to: Mapped[date] = mapped_column(sa.Date)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    issued_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
    issued_by: Mapped[str] = mapped_column(sa.String(64), default="system")
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)

    batch: Mapped[QualificationBatch | None] = relationship(back_populates="items")
    product: Mapped[DataProduct] = relationship()
    project: Mapped[Project] = relationship()


class QuotaAccount(Base):
    """额度账户：已批准预算 + 实际消耗 + 并发占用上限（按课题建账）。"""

    __tablename__ = "quota_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), unique=True, index=True)
    max_concurrent: Mapped[int] = mapped_column(sa.Integer, default=3)      # 并发占用上限
    budget_query: Mapped[int] = mapped_column(sa.Integer, default=0)        # 已批准查询次数
    used_query: Mapped[int] = mapped_column(sa.Integer, default=0)
    budget_export_rows: Mapped[int] = mapped_column(sa.Integer, default=0)  # 已批准导出行数
    used_export_rows: Mapped[int] = mapped_column(sa.Integer, default=0)
    budget_compute_hours: Mapped[float] = mapped_column(sa.Float, default=0)  # 已批准机时
    used_compute_hours: Mapped[float] = mapped_column(sa.Float, default=0)

    project: Mapped[Project] = relationship()


class QuotaReservation(Base):
    """并发占用记录：查询/导出执行期间占用一个并发槽。"""

    __tablename__ = "quota_reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(sa.ForeignKey("quota_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16))  # 查询/导出
    status: Mapped[str] = mapped_column(sa.String(16), default="占用中")  # 占用中/已结算/已释放
    access_event_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    note: Mapped[str] = mapped_column(sa.String(256), default="")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)
    released_at: Mapped[datetime | None] = mapped_column(sa.DateTime, nullable=True)


class UsageEvent(Base):
    """用量事件：一次实际消耗。idempotency_key 全局唯一，重复上报只扣一次。"""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(sa.ForeignKey("quota_accounts.id"), index=True)
    kind: Mapped[str] = mapped_column(sa.String(16))  # 查询/导出/机时
    amount: Mapped[float] = mapped_column(sa.Float, default=1)
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), unique=True, index=True)
    receipt_no: Mapped[str] = mapped_column(sa.String(40), unique=True, index=True)
    access_event_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    balance_after: Mapped[dict] = mapped_column(JSONB, default=dict)  # 扣减后的账户快照
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    reports: Mapped[list["UsageReport"]] = relationship(back_populates="event", order_by="UsageReport.id")


class UsageReport(Base):
    """用量上报记录：每次上报（含断线重试的重复上报）都留痕，重复回执可查。"""

    __tablename__ = "usage_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(sa.ForeignKey("usage_events.id"), index=True)
    is_duplicate: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    note: Mapped[str] = mapped_column(sa.String(256), default="")
    reported_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    event: Mapped[UsageEvent] = relationship(back_populates="reports")


class AccessEvent(Base):
    """数据访问事件：携带当时的产品定义、资格依据与额度变化快照，供审计还原。"""

    __tablename__ = "access_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)  # 客户端请求号，重试幂等
    project_id: Mapped[int] = mapped_column(sa.ForeignKey("projects.id"), index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    purpose_code: Mapped[str] = mapped_column(sa.String(32))
    member_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    member_name: Mapped[str] = mapped_column(sa.String(64))
    qualification_id: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    kind: Mapped[str] = mapped_column(sa.String(16), default="查询")  # 查询/导出
    status: Mapped[str] = mapped_column(sa.String(16))  # 成功/拒绝
    deny_reason: Mapped[str | None] = mapped_column(sa.String(256), nullable=True)
    requested_fields: Mapped[list] = mapped_column(JSONB, default=list)
    granted_fields: Mapped[list] = mapped_column(JSONB, default=list)
    product_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)       # 当时的产品定义
    qualification_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)  # 当时的资格依据
    quota_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)          # 当时的额度变化
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


# ============================ 数据产品批次质量认证 ============================
# 设计要点：
# - 批次清单固定中心、产品分区、字段字典版本与统计时间窗；源记录原样落库，认证只读不改写。
# - 质量规则（硬性数据契约）带版本；分布基线按（产品×分区×字段×字典版本）维护，
#   字典版本不同不拼接计算漂移。
# - 批次更正或规则调整生成新的认证版本，旧认证完整保留；目录引用明确的批次与规则版本。

class DataBatch(Base):
    """数据产品批次：一次到数批次的固定清单（中心/分区/字典版本/统计时间窗）。"""

    __tablename__ = "data_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_no: Mapped[str] = mapped_column(sa.String(40), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    center_code: Mapped[str] = mapped_column(sa.String(32))          # 固定中心
    partition_name: Mapped[str] = mapped_column(sa.String(64))       # 产品分区
    dict_version: Mapped[str] = mapped_column(sa.String(32), index=True)  # 字段字典/代码表版本
    window_from: Mapped[date] = mapped_column(sa.Date)               # 统计时间窗起
    window_to: Mapped[date] = mapped_column(sa.Date)                 # 统计时间窗止
    status: Mapped[str] = mapped_column(sa.String(16), default="待认证")  # 待认证/已认证/已更正
    note: Mapped[str] = mapped_column(sa.String(256), default="")
    created_by: Mapped[str] = mapped_column(sa.String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    records: Mapped[list["BatchRecord"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan", order_by="BatchRecord.id")
    certifications: Mapped[list["QualityCertification"]] = relationship(
        back_populates="batch", order_by="QualityCertification.version.desc()")
    product: Mapped[DataProduct] = relationship()


class BatchRecord(Base):
    """批次源记录：原样留存（payload 不做任何改写），证据样本可回溯到记录主键。

    系统不提供更新/删除端点；批次更正通过新建批次实现，旧记录与旧认证保留。
    """

    __tablename__ = "batch_records"
    __table_args__ = (sa.UniqueConstraint("batch_id", "record_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(sa.ForeignKey("data_batches.id"), index=True)
    record_key: Mapped[str] = mapped_column(sa.String(64))  # 源系统记录主键（如检查编号）
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)  # 源记录原样 JSON
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    batch: Mapped[DataBatch] = relationship(back_populates="records")


class QualityRule(Base):
    """硬性数据契约规则：按（产品 × 字段）维护，调整规则即升规则版本，旧认证快照不受影响。

    rule_type：
      missing     缺失率上限（required=true 时该字段不允许缺失）
      invalid     非法值：值域 enum / 数值范围 / 日期格式与区间
      uniqueness  唯一性：非空记录重复率上限
      consistency 跨字段一致性：成对出现（pair_present）、参考方法与结果范围相容（ref_range）
    params 示例：
      {"required": true, "max_missing_rate": 0.0}
      {"enum": ["CT", "MR", "DR"]} / {"min": 0, "max": 120} / {"date_format": true}
      {"unique": true, "max_duplicate_rate": 0.0}
      {"pair_field": "image_abstract", "max_pair_break_rate": 0.01}
      {"ref_method_field": "ref_method", "ranges": {"酶法": [0, 40], "免疫法": [0, 60]}}
    """

    __tablename__ = "quality_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    field_name: Mapped[str] = mapped_column(sa.String(64), index=True)
    # 规则适用的字段字典版本；NULL 表示与版本无关的通用规则。
    # 字典版本升级的批次只套用同版本/通用规则，避免旧值域误判新代码。
    dict_version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True, index=True)
    rule_type: Mapped[str] = mapped_column(sa.String(16))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    blocking: Mapped[bool] = mapped_column(sa.Boolean, default=True)  # 阻断型规则 vs 观察型
    risk_level: Mapped[str] = mapped_column(sa.String(8), default="中")  # 字段风险：高/中/低
    rule_version: Mapped[int] = mapped_column(sa.Integer, default=1)
    enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    note: Mapped[str] = mapped_column(sa.String(256), default="")
    updated_by: Mapped[str] = mapped_column(sa.String(64), default="system")
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


class DistributionBaseline(Base):
    """历史合格批次建立的分布基线：按（产品×分区×字段×字典版本）隔离。

    字典版本变化时另建基线行，绝不把新旧值域拼接计算漂移。
    stats：分类字段存类目频次分布；数值字段存均值/标准差/分位数/直方图；
           另存成对字段的联合出现比例。
    seasonal_stats：按季节（春/夏/秋/冬）的历史分布，用于识别"合法季节漂移"。
    """

    __tablename__ = "distribution_baselines"
    __table_args__ = (
        sa.UniqueConstraint("product_id", "partition_name", "field_name", "dict_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(sa.ForeignKey("data_products.id"), index=True)
    partition_name: Mapped[str] = mapped_column(sa.String(64), index=True)
    field_name: Mapped[str] = mapped_column(sa.String(64), index=True)
    dict_version: Mapped[str] = mapped_column(sa.String(32))
    sample_size: Mapped[int] = mapped_column(sa.Integer, default=0)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    seasonal_stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_batch_ids: Mapped[list] = mapped_column(JSONB, default=list)  # 基线依据的历史批次
    min_stable_sample: Mapped[int] = mapped_column(sa.Integer, default=30)  # 稳定基线最小样本
    rebuilt_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)


class QualityCertification(Base):
    """批次质量认证版本：同一批次每次（重）认证新增一行，旧版本永不覆盖。"""

    __tablename__ = "quality_certifications"
    __table_args__ = (
        sa.UniqueConstraint("batch_id", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[int] = mapped_column(sa.ForeignKey("data_batches.id"), index=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    rule_version: Mapped[int] = mapped_column(sa.Integer)             # 本次认证引用的规则版本
    # 认证结论：通过 / 有条件通过 / 不通过 / 证据不足
    decision: Mapped[str] = mapped_column(sa.String(16))
    pass_rate: Mapped[float] = mapped_column(sa.Float, default=0.0)   # 字段级通过比例
    field_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    passed_fields: Mapped[int] = mapped_column(sa.Integer, default=0)
    blocked_fields: Mapped[int] = mapped_column(sa.Integer, default=0)
    insufficient_fields: Mapped[int] = mapped_column(sa.Integer, default=0)
    # 该批可供的研究目的与限制（由字段适用等级汇总）
    research_fitness: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[str] = mapped_column(sa.Text, default="")
    trigger: Mapped[str] = mapped_column(sa.String(32), default="首次认证")  # 首次认证/批次更正/规则调整
    created_by: Mapped[str] = mapped_column(sa.String(64), default="system")
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    batch: Mapped[DataBatch] = relationship(back_populates="certifications")
    field_results: Mapped[list["FieldQualityResult"]] = relationship(
        back_populates="certification", cascade="all, delete-orphan",
        order_by="FieldQualityResult.id")


class FieldQualityResult(Base):
    """字段（×分区）质量结果：逐项规则指标、漂移结论、适用等级、阻断原因与证据样本。"""

    __tablename__ = "field_quality_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    certification_id: Mapped[int] = mapped_column(
        sa.ForeignKey("quality_certifications.id"), index=True)
    field_name: Mapped[str] = mapped_column(sa.String(64), index=True)
    partition_name: Mapped[str] = mapped_column(sa.String(64))
    dict_version: Mapped[str] = mapped_column(sa.String(32))
    sample_size: Mapped[int] = mapped_column(sa.Integer, default=0)
    # 适用等级：A 可用于确认性研究 / B 仅限探索性研究 / C 不可用于研究 / I 证据不足
    fitness_grade: Mapped[str] = mapped_column(sa.String(2))
    contract_passed: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    drift_status: Mapped[str] = mapped_column(sa.String(16), default="未评估")  # 无漂移/漂移/证据不足/版本不可比
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)        # 各规则计算指标
    drift_detail: Mapped[dict] = mapped_column(JSONB, default=dict)   # 漂移度量与基线依据
    block_reasons: Mapped[list] = mapped_column(JSONB, default=list)  # 阻断原因（逐条规则/漂移）
    # 证据样本：问题记录主键与样例（可回溯 batch_records 源记录）
    evidence_samples: Mapped[list] = mapped_column(JSONB, default=list)
    rule_refs: Mapped[list] = mapped_column(JSONB, default=list)      # 引用的契约规则 id 与版本
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.utcnow)

    certification: Mapped[QualityCertification] = relationship(back_populates="field_results")
