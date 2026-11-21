"""质量认证演示种子（全部为虚构数据）：

- 硬性数据契约规则（QualityRule，按字段字典版本维护）
- 历史合格批次：经认证引擎逐批认证后形成分布基线（含同季节基线）
- 五个验收场景批次：缺失字段、跨字段矛盾（成对缺失/参考方法矛盾）、
  合法季节漂移、代码表升级、小样本分区
源记录全部经 BatchRecord 原样落库，认证过程不改写任何记录。
"""
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .models import DataBatch, DataProduct, QualityRule, BatchRecord
from .services.quality import certify_batch

DICT_V1 = "DICT-2024.2"
DICT_V2 = "DICT-2026.1"
LAB_PARTITION = "检验常规分区"
IMG_PARTITION = "影像常规分区"
RARE_PARTITION = "稀有队列分区"
CENTER = "CHC-01 总院"

SEASON_MONTH = {"冬": 1, "春": 4, "夏": 7, "秋": 10}


# ----------------------------- 规则维护 -----------------------------

def _rule(db, product_id, field, rtype, params, risk="中", blocking=True,
          dict_version=None, note=""):
    db.add(QualityRule(
        product_id=product_id, field_name=field, rule_type=rtype, params=params,
        blocking=blocking, risk_level=risk, dict_version=dict_version, note=note,
        updated_by="seed"))


def _seed_rules(db: Session, lab_id: int, img_id: int) -> None:
    # ---- P-LAB 检验产品契约（v1 字典） ----
    _rule(db, lab_id, "subject_code", "missing", {"required": True}, "高")
    _rule(db, lab_id, "subject_code", "uniqueness",
          {"unique": True, "max_duplicate_rate": 0.0}, "高")
    _rule(db, lab_id, "patient_name", "missing", {"required": True}, "高")
    _rule(db, lab_id, "test_item", "missing", {"required": True}, "中")
    _rule(db, lab_id, "test_result", "missing",
          {"required": True, "max_missing_rate": 0.02}, "高")
    _rule(db, lab_id, "test_result", "invalid", {"min": 0, "max": 120}, "高")
    _rule(db, lab_id, "test_result", "consistency",
          {"ref_method_field": "ref_method",
           "ranges": {"酶法": [0, 40], "免疫法": [0, 60]},
           "max_contradiction_rate": 0.0}, "高",
          dict_version=DICT_V1,
          note="v1 参考方法范围；计量单位合法不豁免参考方法-结果范围矛盾，v2 字典另建规则")
    _rule(db, lab_id, "test_unit", "invalid",
          {"enum": ["mmol/L", "mg/L", "U/L"]}, "中")
    _rule(db, lab_id, "test_date", "missing", {"required": True}, "中")
    _rule(db, lab_id, "test_date", "invalid", {"date_format": True}, "中")
    _rule(db, lab_id, "age_at_test", "invalid", {"min": 0, "max": 120}, "中")
    _rule(db, lab_id, "abnormal_flag", "invalid",
          {"enum": ["正常", "偏高", "偏低"]}, "中")
    _rule(db, lab_id, "ref_method", "missing", {"required": True}, "中")
    # 值域规则绑定 v1 字典：v2 字典升级后不再套用旧代码表
    _rule(db, lab_id, "ref_method", "invalid",
          {"enum": ["酶法", "免疫法"]}, "中", dict_version=DICT_V1,
          note="v1 代码表；DICT-2026.1 升级为二代方法代码")

    # ---- P-IMG 影像产品契约 ----
    _rule(db, img_id, "exam_id", "missing", {"required": True}, "高")
    _rule(db, img_id, "exam_id", "uniqueness",
          {"unique": True, "max_duplicate_rate": 0.0}, "高")
    _rule(db, img_id, "subject_code", "missing", {"required": True}, "高")
    _rule(db, img_id, "subject_code", "uniqueness",
          {"unique": True, "max_duplicate_rate": 0.0}, "高")
    _rule(db, img_id, "patient_name", "missing", {"required": True}, "高")
    _rule(db, img_id, "patient_id_card", "missing", {"required": True}, "高")
    _rule(db, img_id, "modality", "invalid", {"enum": ["CT", "MR", "DR"]}, "中")
    _rule(db, img_id, "body_part", "missing", {"required": True}, "中")
    _rule(db, img_id, "exam_date", "missing", {"required": True}, "中")
    _rule(db, img_id, "exam_date", "invalid", {"date_format": True}, "中")
    # 检查日期与关键序列必须成对出现：按记录级联合比例报告，禁止分别通过掩盖关系破坏
    _rule(db, img_id, "exam_date", "consistency",
          {"pair_field": "image_abstract", "max_pair_break_rate": 0.01}, "高",
          note="检查日期存在而关键序列缺失即联合关系破坏")
    _rule(db, img_id, "report_text", "missing",
          {"required": True, "max_missing_rate": 0.05}, "中")


# ----------------------------- 记录生成器（确定性虚构数据） -----------------------------

ITEMS = ["血糖", "肌酐", "ALT", "总胆固醇"]
METHODS = ["酶法", "免疫法"]
FLAGS = ["正常", "偏高", "偏低"]
MODALITIES = ["CT", "MR", "DR"]
BODY_PARTS = ["胸部", "腹部"]


def _lab_row(i: int, w_from: date, *, elevated=False, prefix="S") -> dict:
    result = round(9.0 + ((i * 29) % 31) / 10.0, 2) if elevated else \
        round(4.0 + ((i * 37) % 41) / 10.0, 2)  # 4.0~8.0 / 9.0~12.0
    return {
        "subject_code": f"{prefix}{10000 + i:06d}",
        "patient_name": f"患者{i:03d}",
        "test_item": ITEMS[i % len(ITEMS)],
        "test_result": result,
        "test_unit": "mmol/L",
        "test_date": (w_from + timedelta(days=i % 20)).isoformat(),
        "age_at_test": 30 + (i * 13) % 40,
        "abnormal_flag": FLAGS[i % len(FLAGS)],
        "ref_method": METHODS[i % 2],
    }


def _img_row(i: int, w_from: date) -> dict:
    return {
        "exam_id": f"E{20000 + i:06d}",
        "subject_code": f"S{30000 + i:06d}",
        "patient_name": f"影像患者{i:03d}",
        "patient_id_card": f"ID{i:06d}X",
        "modality": MODALITIES[i % 3],
        "body_part": BODY_PARTS[i % 2],
        "exam_date": (w_from + timedelta(days=i % 20)).isoformat(),
        "image_abstract": {"sequence": ["T1", "T2"], "features": [0.12 * (i % 5), 0.31]},
        "report_text": f"影像所见与诊断结论（演示记录 {i}）",
    }


def _add_batch(db: Session, *, batch_no: str, product_id: int, partition: str,
               dict_version: str, w_from: date, w_to: str | date, note: str,
               records: list[dict], certify: bool = True,
               establish_baseline: bool = False) -> DataBatch:
    if isinstance(w_to, str):
        w_to = date.fromisoformat(w_to)
    batch = DataBatch(
        batch_no=batch_no, product_id=product_id, center_code=CENTER,
        partition_name=partition, dict_version=dict_version,
        window_from=w_from, window_to=w_to, note=note, created_by="seed")
    db.add(batch)
    db.flush()
    for i, payload in enumerate(records):
        natural = payload.get("exam_id") or payload.get("subject_code")
        # 自然键缺失本身是数据质量问题，但记录主键仍须唯一可追溯：回退到行位键
        record_key = natural or f"{batch_no}-ROW-{i + 1:04d}"
        db.add(BatchRecord(batch_id=batch.id, record_key=record_key, payload=payload))
    db.flush()
    if certify:
        certify_batch(db, batch, "首次认证", "seed",
                      establish_baseline=establish_baseline)
    return batch


# ----------------------------- 主入口 -----------------------------

def seed_quality(db: Session) -> None:
    lab = db.query(DataProduct).filter(DataProduct.code == "P-LAB").one()
    img = db.query(DataProduct).filter(DataProduct.code == "P-IMG").one()
    _seed_rules(db, lab.id, img.id)
    db.flush()

    today = date.today()
    cur_season = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春",
                  6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋"}[today.month]
    same_season_month = SEASON_MONTH[cur_season]

    # 常规历史批次只放在"其他三个季节"，确保当前季节的季节基线只由同模式（季节性偏高）批次构成
    other_months = [m for m in [3, 6, 9, 12, 4, 7, 10, 5, 8]
                    if {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春",
                        6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋",
                        11: "秋"}[m] != cur_season][:4]

    # ---- 历史合格批次（其他季节常规批 + 当前季节两批复现季节模式）----
    history_plan = []
    for idx, month in enumerate(other_months, start=1):
        year = 2024 if month == 12 else 2025
        history_plan.append(
            (f"DQ-HIST-LAB-{idx:02d}", date(year, month, 10),
             date(year, month, 28), False))
    # 与当前批次同季节的两批：test_result 季节性偏高（可复现的季节模式）
    sy = today.year - 1
    history_plan += [
        ("DQ-HIST-LAB-05", date(sy, same_season_month, 10),
         date(sy, same_season_month, 28), True),
        ("DQ-HIST-LAB-06", date(today.year, same_season_month, 5),
         date(today.year, same_season_month, 22), True),
    ]
    for no, wf, wt, elevated in history_plan:
        rows = [_lab_row(i, wf, elevated=elevated, prefix=f"H{no[-2:]}") for i in range(40)]
        _add_batch(db, batch_no=no, product_id=lab.id, partition=LAB_PARTITION,
                   dict_version=DICT_V1, w_from=wf, w_to=wt,
                   note="历史合格批次（分布基线依据）", records=rows,
                   establish_baseline=True)

    # 影像历史两批（含一批同季节），支撑影像分区基线
    img_hist = [
        ("DQ-HIST-IMG-01", date(2025, 4, 15), date(2025, 4, 30)),
        ("DQ-HIST-IMG-02", date(today.year - 1, same_season_month, 12),
         date(today.year - 1, same_season_month, 28)),
    ]
    for no, wf, wt in img_hist:
        rows = [_img_row(i, wf) for i in range(40)]
        _add_batch(db, batch_no=no, product_id=img.id, partition=IMG_PARTITION,
                   dict_version=DICT_V1, w_from=wf, w_to=wt,
                   note="历史合格批次（影像分区基线依据）", records=rows,
                   establish_baseline=True)

    # ---- 场景 0：同季节模式合格批次（契约全过、漂移被同季节基线解释，全部 A）----
    wf = today - timedelta(days=6)
    _add_batch(db, batch_no="DQ-CUR-LAB-OK", product_id=lab.id,
               partition=LAB_PARTITION, dict_version=DICT_V1,
               w_from=wf, w_to=today - timedelta(days=1),
               note="对照批次：同季节模式，契约全过且无不可解释漂移，全部字段 A 级",
               records=[_lab_row(i, wf, elevated=True, prefix="OK") for i in range(40)])

    # ---- 场景 1：缺失字段 + 非法值 + 参考方法矛盾 ----
    rows = [_lab_row(i, wf, prefix="M1") for i in range(40)]
    for i in range(8):  # 关键字段 test_result 缺失（超 2% 契约上限）
        rows[i]["test_result"] = None
    for i in range(10, 13):  # 必需字段 subject_code 缺失
        rows[i]["subject_code"] = ""
    rows[20]["abnormal_flag"] = "未知"      # 非法枚举
    rows[21]["abnormal_flag"] = "异常++"    # 非法枚举
    rows[22]["test_result"] = 150.0         # 超数值上限
    rows[23]["test_result"] = 45.0          # 酶法合法范围 0~40，矛盾
    rows[23]["ref_method"] = "酶法"
    rows[24]["test_result"] = 65.0          # 免疫法合法范围 0~60，矛盾
    rows[24]["ref_method"] = "免疫法"
    _add_batch(db, batch_no="DQ-CUR-LAB-MISSING", product_id=lab.id,
               partition=LAB_PARTITION, dict_version=DICT_V1,
               w_from=wf, w_to=today - timedelta(days=1),
               note="验收样例：缺失字段/非法值/参考方法-结果范围矛盾", records=rows)

    # ---- 场景 2：影像检查日期存在而关键序列缺失（记录级联合比例）----
    img_rows = [_img_row(i, wf) for i in range(40)]
    for i in range(10):  # exam_date 仍在，image_abstract 缺失 → 成对关系破坏
        img_rows[i]["image_abstract"] = None
    _add_batch(db, batch_no="DQ-CUR-IMG-PAIR", product_id=img.id,
               partition=IMG_PARTITION, dict_version=DICT_V1,
               w_from=wf, w_to=today - timedelta(days=1),
               note="验收样例：检查日期存在但关键序列缺失（成对字段联合校验）",
               records=img_rows)

    # ---- 场景 3：合法季节漂移（同季节基线可解释，总体基线超阈）----
    _add_batch(db, batch_no="DQ-CUR-LAB-SEASON", product_id=lab.id,
               partition=LAB_PARTITION, dict_version=DICT_V1,
               w_from=wf, w_to=today - timedelta(days=1),
               note="验收样例：test_result 季节性偏高，同季节基线判定为合法季节漂移",
               records=[_lab_row(i, wf, elevated=True, prefix="SN") for i in range(40)])

    # ---- 场景 4：代码表升级（DICT-2026.1，新旧值域不拼接漂移）----
    upgraded = [_lab_row(i, wf, prefix="V2") for i in range(40)]
    for r in upgraded:  # 二代方法新代码：v1 枚举规则不再适用，v2 暂无基线
        r["ref_method"] = "酶法-二代" if r["ref_method"] == "酶法" else "免疫法-二代"
    _add_batch(db, batch_no="DQ-CUR-LAB-DICT-V2", product_id=lab.id,
               partition=LAB_PARTITION, dict_version=DICT_V2,
               w_from=wf, w_to=today - timedelta(days=1),
               note="验收样例：字段字典/代码表升级，漂移按版本隔离不拼接", records=upgraded)

    # ---- 场景 5：小样本分区（8 条，证据不足，不推断无漂移）----
    _add_batch(db, batch_no="DQ-CUR-LAB-RARE", product_id=lab.id,
               partition=RARE_PARTITION, dict_version=DICT_V1,
               w_from=wf, w_to=today - timedelta(days=1),
               note="验收样例：稀有队列分区样本不足，认证标证据不足",
               records=[_lab_row(i, wf, prefix="RR") for i in range(8)])
