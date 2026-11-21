"""演示种子数据（全部为虚构输入）：产品目录、课题档案、伦理批件、成员、
额度账户、首批资格实例与一次示范访问。幂等：已有用户时跳过。"""
import uuid
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .models import (
    AccessEvent, DataProduct, EthicsApproval, ProductField, Project,
    ProjectMember, ProjectPurpose, QualificationBatch, QualificationInstance,
    QuotaAccount, QuotaReservation, User,
)
from .security import hash_password
from .services import quota as quota_svc
from .services.compiler import compile_qualification

TODAY = date.today()
D = timedelta(days=1)


def _product(db, code, name, source, freq, dept, desc, fields):
    p = DataProduct(
        code=code, name=name, source_system=source, update_frequency=freq,
        owner_dept=dept, description=desc,
    )
    db.add(p)
    db.flush()
    for f in fields:
        db.add(ProductField(product_id=p.id, **f))
    db.flush()
    return p


def seed(db: Session) -> None:
    # ---------------- 用户（测试账号） ----------------
    users = [
        User(username="admin", password_hash=hash_password("admin123"),
             display_name="林治理", role="ADMIN"),
        User(username="wangjianguo", password_hash=hash_password("wang123"),
             display_name="王建国", role="PI", member_name="王建国"),
        User(username="zhangmin", password_hash=hash_password("zhang123"),
             display_name="张敏", role="ANALYST", member_name="张敏"),
        User(username="zhaolei", password_hash=hash_password("zhao123"),
             display_name="赵磊", role="ANALYST", member_name="赵磊"),
        User(username="auditor", password_hash=hash_password("audit123"),
             display_name="沈审计", role="AUDITOR"),
    ]
    db.add_all(users)

    # ---------------- 产品目录 ----------------
    default_win = {"available_from": date(2020, 1, 1), "available_to": date(2027, 12, 31)}
    p_img = _product(db, "P-IMG", "影像检查数据产品", "PACS 影像系统", "每日",
                     "影像科", "胸部/腹部影像检查记录与影像组学特征", [
        {"field_name": "exam_id", "semantic": "检查编号", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "subject_code", "semantic": "受试者编号（已脱敏）", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "patient_name", "semantic": "患者姓名", "data_type": "string",
         "sensitivity_level": 4, "tags": ["直接标识符"], **default_win},
        {"field_name": "patient_id_card", "semantic": "身份证号", "data_type": "string",
         "sensitivity_level": 4, "tags": ["直接标识符"], **default_win},
        {"field_name": "modality", "semantic": "检查模态（CT/MR/DR）", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "body_part", "semantic": "检查部位", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "exam_date", "semantic": "检查日期", "data_type": "date",
         "sensitivity_level": 3, "tags": ["准标识符"], **default_win},
        {"field_name": "image_abstract", "semantic": "影像组学特征摘要（2023年中上线）",
         "data_type": "json", "sensitivity_level": 3, "tags": [],
         "available_from": date(2023, 6, 1), "available_to": date(2027, 12, 31)},
        {"field_name": "report_text", "semantic": "影像报告全文", "data_type": "text",
         "sensitivity_level": 3, "tags": [], **default_win},
    ])
    p_lab = _product(db, "P-LAB", "检验指标数据产品", "LIS 检验系统", "每日",
                     "检验科", "临床检验项目与结果指标", [
        {"field_name": "subject_code", "semantic": "受试者编号（已脱敏）", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "patient_name", "semantic": "患者姓名", "data_type": "string",
         "sensitivity_level": 4, "tags": ["直接标识符"], **default_win},
        {"field_name": "test_item", "semantic": "检验项目名称", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "test_result", "semantic": "检验结果值", "data_type": "number",
         "sensitivity_level": 3, "tags": [],
         "available_from": date(2019, 1, 1), "available_to": date(2026, 12, 31)},
        {"field_name": "test_unit", "semantic": "计量单位", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "test_date", "semantic": "检验日期", "data_type": "date",
         "sensitivity_level": 3, "tags": ["准标识符"], **default_win},
        {"field_name": "age_at_test", "semantic": "检验时年龄", "data_type": "number",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "abnormal_flag", "semantic": "异常标记", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "ref_method", "semantic": "检验参考方法（酶法/免疫法等，决定结果参考范围）",
         "data_type": "string", "sensitivity_level": 1, "tags": [], **default_win},
    ])
    p_fu = _product(db, "P-FU", "随访记录数据产品", "随访管理平台", "每周",
                    "临床研究部", "出院后随访、生存状态与复发记录", [
        {"field_name": "followup_no", "semantic": "随访编号", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "subject_code", "semantic": "受试者编号（已脱敏）", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "followup_date", "semantic": "随访日期", "data_type": "date",
         "sensitivity_level": 3, "tags": ["准标识符"], **default_win},
        {"field_name": "survival_status", "semantic": "生存状态", "data_type": "string",
         "sensitivity_level": 3, "tags": [], **default_win},
        {"field_name": "recurrence_flag", "semantic": "复发标记", "data_type": "boolean",
         "sensitivity_level": 3, "tags": [], **default_win},
        {"field_name": "contact_phone", "semantic": "联系电话", "data_type": "string",
         "sensitivity_level": 4, "tags": ["直接标识符"], **default_win},
        {"field_name": "followup_note", "semantic": "随访备注", "data_type": "text",
         "sensitivity_level": 3, "tags": [], **default_win},
    ])
    p_bio = _product(db, "P-BIO", "样本库数据产品", "样本库管理系统", "每月",
                     "生物样本库", "样本库存、质控与标志物检测", [
        {"field_name": "sample_id", "semantic": "样本编号", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "subject_code", "semantic": "受试者编号（已脱敏）", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "sample_type", "semantic": "样本类型（血清/组织）", "data_type": "string",
         "sensitivity_level": 1, "tags": [], **default_win},
        {"field_name": "collect_date", "semantic": "采集日期", "data_type": "date",
         "sensitivity_level": 3, "tags": ["准标识符"], **default_win},
        {"field_name": "storage_location", "semantic": "存储位置", "data_type": "string",
         "sensitivity_level": 2, "tags": [], **default_win},
        {"field_name": "gene_marker", "semantic": "基因标志物检测结果", "data_type": "json",
         "sensitivity_level": 4, "tags": ["遗传信息"], **default_win},
        {"field_name": "quality_score", "semantic": "样本质控评分", "data_type": "number",
         "sensitivity_level": 1, "tags": [], **default_win},
    ])

    # ---------------- 课题档案（用途条件 / 成员 / 伦理批件） ----------------
    prj_a = Project(code="PRJ-A", name="冠心病预后模型研究", pi_name="王建国",
                    status="在研", start_date=TODAY - 400 * D, end_date=TODAY + 500 * D)
    db.add(prj_a); db.flush()
    db.add_all([
        ProjectPurpose(project_id=prj_a.id, purpose_code="TRAIN",
                       description="预后模型训练：需要 L3 级临床与检验明细，禁止直接标识符",
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       export_allowed=True),
        ProjectPurpose(project_id=prj_a.id, purpose_code="PUBLISH",
                       description="统计结果发表：仅 L2 级汇总字段，禁止标识符与准标识符，不允许导出",
                       max_sensitivity_level=2,
                       forbidden_tags=["直接标识符", "准标识符"], export_allowed=False),
        ProjectMember(project_id=prj_a.id, name="王建国", role="PI",
                      valid_from=TODAY - 400 * D, valid_to=TODAY + 500 * D),
        ProjectMember(project_id=prj_a.id, name="张敏", role="数据分析师",
                      valid_from=TODAY - 400 * D, valid_to=TODAY + 500 * D),
        ProjectMember(project_id=prj_a.id, name="赵磊", role="统计师",
                      valid_from=TODAY - 400 * D, valid_to=TODAY + 500 * D),
        ProjectMember(project_id=prj_a.id, name="孙倩", role="研究员",
                      valid_from=TODAY - 400 * D, valid_to=TODAY - 30 * D, status="离任"),
        EthicsApproval(project_id=prj_a.id, approval_no="EA-2025-001",
                       scope_subjects="2018 年以来心内科住院冠心病患者队列",
                       allowed_purposes=["TRAIN", "PUBLISH"],
                       max_sensitivity_level=3,
                       forbidden_tags=["直接标识符", "遗传信息"],
                       valid_from=TODAY - 300 * D, valid_to=TODAY + 400 * D),
    ])

    prj_b = Project(code="PRJ-B", name="影像组学标志物探索", pi_name="陈静",
                    status="在研", start_date=TODAY - 200 * D, end_date=TODAY + 300 * D)
    db.add(prj_b); db.flush()
    db.add_all([
        ProjectPurpose(project_id=prj_b.id, purpose_code="EXTRACT",
                       description="影像特征提取：L3 级影像数据，禁止直接标识符",
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       export_allowed=True),
        ProjectMember(project_id=prj_b.id, name="陈静", role="PI",
                      valid_from=TODAY - 200 * D, valid_to=TODAY + 300 * D),
        # 张敏同时是两个课题的成员 —— 用于验证跨课题资格边界
        ProjectMember(project_id=prj_b.id, name="张敏", role="数据分析师",
                      valid_from=TODAY - 200 * D, valid_to=TODAY + 300 * D),
        EthicsApproval(project_id=prj_b.id, approval_no="EA-2025-002",
                       scope_subjects="肺结节影像回顾性队列",
                       allowed_purposes=["EXTRACT"],
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       valid_from=TODAY - 200 * D, valid_to=TODAY + 300 * D),
    ])

    prj_c = Project(code="PRJ-C", name="旧队列回顾性分析", pi_name="刘洋",
                    status="在研", start_date=TODAY - 700 * D, end_date=TODAY + 100 * D)
    db.add(prj_c); db.flush()
    db.add_all([
        ProjectPurpose(project_id=prj_c.id, purpose_code="REVIEW",
                       description="回顾性分析：L3 级历史数据",
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       export_allowed=False),
        ProjectMember(project_id=prj_c.id, name="刘洋", role="PI",
                      valid_from=TODAY - 700 * D, valid_to=TODAY + 100 * D),
        ProjectMember(project_id=prj_c.id, name="周杰", role="研究员",
                      valid_from=TODAY - 700 * D, valid_to=TODAY + 100 * D),
        # 伦理批件已过期失效 —— 用于验证批次处理中伦理失效不得签发
        EthicsApproval(project_id=prj_c.id, approval_no="EA-2024-003",
                       scope_subjects="2015-2020 年体检队列",
                       allowed_purposes=["REVIEW"],
                       max_sensitivity_level=3, forbidden_tags=["直接标识符"],
                       valid_from=TODAY - 700 * D, valid_to=TODAY - 400 * D,
                       status="失效"),
    ])

    # ---------------- 额度账户（已批准预算 + 并发上限） ----------------
    db.add_all([
        QuotaAccount(project_id=prj_a.id, max_concurrent=3, budget_query=500,
                     budget_export_rows=20000, budget_compute_hours=100),
        QuotaAccount(project_id=prj_b.id, max_concurrent=2, budget_query=200,
                     budget_export_rows=5000, budget_compute_hours=50),
        QuotaAccount(project_id=prj_c.id, max_concurrent=1, budget_query=50,
                     budget_export_rows=1000, budget_compute_hours=10),
    ])
    db.flush()

    # ---------------- 首批资格实例（通过编译器签发，保证与求交逻辑一致） ----------------
    batch = QualificationBatch(batch_no="B-SEED-0001", title="开通前首批资格签发",
                               created_by="seed", total=0, succeeded=0, failed=0)
    db.add(batch); db.flush()
    plan = [
        (prj_a, p_lab, "TRAIN"), (prj_a, p_lab, "PUBLISH"),
        (prj_a, p_img, "TRAIN"), (prj_b, p_img, "EXTRACT"),
    ]
    for project, product, purpose_code in plan:
        compiled = compile_qualification(db, project, product, purpose_code, TODAY)
        db.add(QualificationInstance(
            batch_id=batch.id, project_id=project.id, product_id=product.id,
            purpose_code=purpose_code, status="已签发",
            field_projection=compiled.field_projection,
            covered_member_ids=compiled.covered_member_ids,
            basis=compiled.basis, catalog_version=compiled.catalog_version,
            valid_from=compiled.valid_from, valid_to=compiled.valid_to,
            issued_by="seed",
        ))
        batch.succeeded += 1
        batch.total += 1
    batch.status = "完成"
    db.flush()

    # ---------------- 一次示范访问（张敏 在 PRJ-A 用 TRAIN 查询 P-LAB） ----------------
    qual = (
        db.query(QualificationInstance)
        .filter(QualificationInstance.project_id == prj_a.id,
                QualificationInstance.product_id == p_lab.id,
                QualificationInstance.purpose_code == "TRAIN",
                QualificationInstance.status == "已签发")
        .one()
    )
    member_zm_a = db.query(ProjectMember).filter(
        ProjectMember.project_id == prj_a.id, ProjectMember.name == "张敏").one()
    request_id = "seed-demo-0001"
    reservation = quota_svc.acquire(db, prj_a.id, "查询", note="种子示范访问")
    usage, _ = quota_svc.report_usage(db, prj_a.id, "查询", 1,
                                      idempotency_key=f"access:{request_id}",
                                      note="种子示范访问消耗")
    quota_svc.release(db, reservation, status="已结算")
    granted = qual.field_projection
    event = AccessEvent(
        request_id=request_id, project_id=prj_a.id, product_id=p_lab.id,
        purpose_code="TRAIN", member_id=member_zm_a.id, member_name="张敏",
        qualification_id=qual.id, kind="查询", status="成功",
        requested_fields=[], granted_fields=granted,
        product_snapshot={
            "id": p_lab.id, "code": p_lab.code, "name": p_lab.name,
            "source_system": p_lab.source_system,
            "update_frequency": p_lab.update_frequency,
            "catalog_version": p_lab.catalog_version,
            "fields": [
                {"field_name": f.field_name, "semantic": f.semantic,
                 "data_type": f.data_type, "sensitivity_level": f.sensitivity_level,
                 "tags": f.tags, "available_from": f.available_from.isoformat(),
                 "available_to": f.available_to.isoformat(), "is_active": f.is_active}
                for f in p_lab.fields
            ],
        },
        qualification_snapshot={
            "id": qual.id, "purpose_code": qual.purpose_code, "status": qual.status,
            "valid_from": qual.valid_from.isoformat(), "valid_to": qual.valid_to.isoformat(),
            "catalog_version": qual.catalog_version,
            "field_projection": qual.field_projection,
            "covered_member_ids": qual.covered_member_ids,
            "basis": qual.basis,
        },
        quota_snapshot={
            "reservation_id": reservation.id, "usage_event_id": usage.id,
            "receipt_no": usage.receipt_no,
            "consumed": {"kind": "查询", "amount": 1},
            "balance_after": usage.balance_after, "rejected_fields": [],
        },
    )
    db.add(event); db.flush()
    reservation.access_event_id = event.id
    usage.access_event_id = event.id
    db.flush()

    # ---------------- 批次质量认证演示数据（契约规则/历史基线/五类验收场景） ----------------
    from .seed_quality import seed_quality
    seed_quality(db)
    db.commit()
