"""数据产品批次质量认证引擎。

两条互补的判定路线，按字段风险与历史基线代表性组合使用：

1. 硬性数据契约（QualityRule）：逐项校验缺失、非法值、唯一性、跨字段一致性。
   结果稳定、解释直接；阻断型规则失败的字段直接判 C（不可用于研究），
   不允许被批次总体通过率稀释放行。
2. 历史合格批次分布基线（DistributionBaseline）：同字典版本内计算分布漂移
   （分类字段 TV 距离/比例 z 检验，数值字段均值 z 检验/PSI），并以同季节基线
   识别"合法季节漂移"。字典版本不同不拼接值域；样本不足一律标"证据不足"，
   绝不推断无漂移。

不变量：
- 源记录（BatchRecord.payload）只读，引擎只计算不改写；证据样本以 record_key 回溯。
- 每次认证生成新的 QualityCertification 版本，旧版本与旧字段结果完整保留。
"""
from __future__ import annotations

import math
import uuid
from bisect import bisect_right
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from ..models import (
    DataBatch, DistributionBaseline, FieldQualityResult, ProductField,
    QualityCertification, QualityRule,
)

# 稳定基线/本批最小样本：低于该值不做漂移推断
MIN_STABLE_SAMPLE = 30
# 漂移阈值：TV 距离、PSI、双侧 z（≈p<0.01）
TV_DRIFT_THRESHOLD = 0.20
PSI_DRIFT_THRESHOLD = 0.25
Z_DRIFT_THRESHOLD = 2.58
# 证据样本每字段最多留存条数
EVIDENCE_CAP = 10
# 高基数标识字段（distinct/非空 > 该比例）不做分布漂移
IDENTIFIER_DISTINCT_RATIO = 0.8

FITNESS_LABELS = {
    "A": "A 可用于确认性研究",
    "B": "B 仅限探索性研究",
    "C": "C 不可用于研究",
    "I": "I 证据不足",
}

SEASONS = {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春",
           6: "夏", 7: "夏", 8: "夏", 9: "秋", 10: "秋", 11: "秋"}


class QualityError(Exception):
    """认证过程不可恢复的输入错误。"""


# ----------------------------- 基础工具 -----------------------------

def _is_missing(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    if isinstance(v, (list, dict)) and len(v) == 0:
        return True
    return False


def _to_float(v):
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _season_of(d: date) -> str:
    return SEASONS[d.month]


def _rate(x: int, n: int) -> float:
    return round(x / n, 6) if n else 0.0


def _field_kind(field: ProductField) -> str:
    return "numeric" if field.data_type == "number" else "categorical"


def _category_value(field: ProductField, v):
    """分类字段的漂移分组键：日期按年月聚合，其余按原值。"""
    if field.data_type == "date" and isinstance(v, str) and len(v) >= 7:
        return v[:7]
    return v


# ----------------------------- 分布统计 -----------------------------

def _numeric_stats(values: list[float]) -> dict:
    n = len(values)
    if n == 0:
        return {"kind": "numeric", "n": 0}
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / n
    std = math.sqrt(var)
    ordered = sorted(values)
    # 十分位分箱（固定边界，后续批次沿用同一组边界计算 PSI）
    edges = [ordered[0]]
    for q in range(1, 10):
        edges.append(ordered[min(n - 1, math.ceil(q * n / 10) - 1)])
    edges.append(ordered[-1])
    # 去重并保持递增
    uniq = []
    for e in edges:
        if not uniq or e > uniq[-1]:
            uniq.append(e)
    edges = uniq
    hist = [0] * (len(edges) - 1)
    for x in values:
        idx = bisect_right(edges, x) - 1
        if idx >= len(hist):
            idx = len(hist) - 1
        hist[idx] += 1
    return {"kind": "numeric", "n": n, "mean": mean, "std": std,
            "edges": edges, "hist": hist}


def _categorical_stats(values: list) -> dict:
    freq: dict = {}
    for v in values:
        key = str(v)
        freq[key] = freq.get(key, 0) + 1
    return {"kind": "categorical", "n": len(values), "freq": freq}


def _field_values(field: ProductField, rows: list[tuple[str, dict]], *, present_only=True):
    out = []
    for key, payload in rows:
        v = payload.get(field.field_name)
        if present_only and _is_missing(v):
            continue
        out.append(v)
    return out


# ----------------------------- 漂移度量 -----------------------------

def _two_prop_z(x1: int, n1: int, x2: int, n2: int) -> float:
    if n1 == 0 or n2 == 0:
        return 0.0
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    denom = math.sqrt(max(p * (1 - p) * (1 / n1 + 1 / n2), 1e-12))
    return (p1 - p2) / denom


def _categorical_drift(base: dict, cur: dict) -> dict:
    """TV 距离 + 逐类目双比例 z 检验。"""
    bf, cf = base["freq"], cur["freq"]
    keys = set(bf) | set(cf)
    bn, cn = base["n"], cur["n"]
    tv = 0.0
    z_hits = []
    for k in sorted(keys):
        p_b = bf.get(k, 0) / bn if bn else 0.0
        p_c = cf.get(k, 0) / cn if cn else 0.0
        tv += abs(p_b - p_c)
        z = _two_prop_z(cf.get(k, 0), cn, bf.get(k, 0), bn)
        if abs(z) >= Z_DRIFT_THRESHOLD and abs(p_c - p_b) >= 0.05:
            z_hits.append({"category": k, "baseline_rate": round(p_b, 4),
                           "current_rate": round(p_c, 4), "z": round(z, 3)})
    tv = round(tv / 2, 6)
    drifted = tv >= TV_DRIFT_THRESHOLD or bool(z_hits)
    return {"method": "TV+比例z", "tv_distance": tv, "z_hits": z_hits,
            "thresholds": {"tv": TV_DRIFT_THRESHOLD, "z": Z_DRIFT_THRESHOLD},
            "drifted": drifted}


def _psi(base_hist: list[int], cur_hist: list[int], edges: list) -> tuple[float, list]:
    bn, cn = sum(base_hist), sum(cur_hist)
    detail = []
    psi = 0.0
    for i in range(len(edges) - 1):
        p = (base_hist[i] / bn) if bn else 0.0
        q = (cur_hist[i] / cn) if cn else 0.0
        ps, qs = max(p, 1e-6), max(q, 1e-6)
        contrib = (q - p) * math.log(qs / ps)
        psi += contrib
        detail.append({"bin": f"[{edges[i]}, {edges[i + 1]}]",
                       "baseline_rate": round(p, 4), "current_rate": round(q, 4),
                       "psi_contribution": round(contrib, 6)})
    return round(psi, 6), detail


def _numeric_drift(base: dict, cur: dict, cur_values: list[float] | None = None) -> dict:
    """base/cur 均为统计字典。PSI 必须用该基线自己的固定边界对当前原始值重新分箱，
    不能复用按其他边界分好的直方图，否则边界错配会产生虚假 PSI。"""
    z_mean = 0.0
    if base.get("std") and cur.get("n"):
        z_mean = (cur["mean"] - base["mean"]) / max(base["std"] / math.sqrt(cur["n"]), 1e-12)
    edges = base["edges"]
    bin_detail = []
    psi = None
    if cur_values is not None:
        cur_hist = [0] * (len(edges) - 1)
        for x in cur_values:
            idx = max(0, min(bisect_right(edges, x) - 1, len(cur_hist) - 1))
            cur_hist[idx] += 1
        psi, bin_detail = _psi(base["hist"], cur_hist, edges)
    drifted = abs(z_mean) >= Z_DRIFT_THRESHOLD or (psi is not None and psi >= PSI_DRIFT_THRESHOLD)
    return {"method": "均值z+PSI", "mean_z": round(z_mean, 3),
            "psi": psi if psi is not None else "不可用（缺少当前原始值重分箱）",
            "baseline_mean": round(base["mean"], 4), "current_mean": round(cur["mean"], 4),
            "baseline_std": round(base.get("std", 0), 4),
            "thresholds": {"z": Z_DRIFT_THRESHOLD, "psi": PSI_DRIFT_THRESHOLD},
            "bin_detail": bin_detail, "drifted": drifted}


def _drift_against(base_stats: dict, cur_stats: dict,
                   cur_values: list | None = None) -> dict | None:
    if base_stats.get("n", 0) == 0:
        return None
    if base_stats["kind"] == "categorical":
        return _categorical_drift(base_stats, cur_stats)
    return _numeric_drift(base_stats, cur_stats, cur_values)


# ----------------------------- 基线 -----------------------------

def _qualified_history_batches(db: Session, product_id: int, partition: str,
                               dict_version: str,
                               exclude_batch_id: int | None = None) -> list[DataBatch]:
    """已确认合格（最新认证版本为 通过/有条件通过）的历史批次。"""
    batches = (
        db.query(DataBatch)
        .filter(DataBatch.product_id == product_id,
                DataBatch.partition_name == partition,
                DataBatch.dict_version == dict_version)
        .order_by(DataBatch.id)
        .all()
    )
    ok = []
    for b in batches:
        if exclude_batch_id is not None and b.id == exclude_batch_id:
            continue  # 认证时不得把本批纳入自身基线
        latest = b.certifications[0] if b.certifications else None
        if latest and latest.decision in ("通过", "有条件通过"):
            ok.append(b)
    return ok


def rebuild_baseline(db: Session, product_id: int, partition: str, field_name: str,
                     dict_version: str,
                     exclude_batch_id: int | None = None) -> DistributionBaseline | None:
    """从同字典版本的合格历史批次重建（产品×分区×字段）分布基线，含分季节基线。

    字典版本不同的批次不参与——基线本身按 dict_version 隔离，绝不拼接新旧值域。
    """
    field = (
        db.query(ProductField)
        .filter(ProductField.product_id == product_id,
                ProductField.field_name == field_name)
        .first()
    )
    if field is None:
        raise QualityError(f"字段 {field_name} 不在产品字段字典中")

    batches = _qualified_history_batches(
        db, product_id, partition, dict_version, exclude_batch_id=exclude_batch_id)
    if not batches:
        return None

    all_rows: list[tuple[str, dict]] = []
    season_rows: dict[str, list] = {}
    for b in batches:
        rows = [(r.record_key, r.payload) for r in b.records]
        season = _season_of(b.window_from)
        season_rows.setdefault(season, []).extend(rows)
        all_rows.extend(rows)

    kind = _field_kind(field)
    if field.data_type == "date":
        # 日期类字段以契约（格式/区间/成对出现）约束，绝对年月分布不具漂移可比性
        stats = {"kind": "date", "n": len(_field_values(field, all_rows))}
        seasonal = {s: {"kind": "date", "n": len(_field_values(field, rows))}
                    for s, rows in season_rows.items()}
    elif kind == "numeric":
        values = [x for x in _field_values(field, all_rows) if _to_float(x) is not None]
        stats = _numeric_stats([_to_float(x) for x in values])
        seasonal = {}
        for season, rows in season_rows.items():
            vals = [_to_float(x) for x in _field_values(field, rows) if _to_float(x) is not None]
            seasonal[season] = _numeric_stats(vals)
    else:
        raw = _field_values(field, all_rows)
        # 高基数标识字段不建分布基线
        distinct = len({str(v) for v in raw})
        if raw and distinct / len(raw) >= IDENTIFIER_DISTINCT_RATIO:
            stats = {"kind": "identifier", "n": len(raw), "distinct": distinct}
        else:
            stats = _categorical_stats([_category_value(field, v) for v in raw])
        seasonal = {}
        for season, rows in season_rows.items():
            vals = _field_values(field, rows)
            seasonal[season] = _categorical_stats(
                [_category_value(field, v) for v in vals])

    baseline = (
        db.query(DistributionBaseline)
        .filter(DistributionBaseline.product_id == product_id,
                DistributionBaseline.partition_name == partition,
                DistributionBaseline.field_name == field_name,
                DistributionBaseline.dict_version == dict_version)
        .first()
    )
    if baseline is None:
        baseline = DistributionBaseline(
            product_id=product_id, partition_name=partition, field_name=field_name,
            dict_version=dict_version)
        db.add(baseline)
    baseline.sample_size = stats.get("n", 0)
    baseline.stats = stats
    baseline.seasonal_stats = seasonal
    baseline.source_batch_ids = [b.id for b in batches]
    baseline.min_stable_sample = MIN_STABLE_SAMPLE
    baseline.rebuilt_at = datetime.utcnow()
    db.flush()
    return baseline


# ----------------------------- 契约规则评估 -----------------------------

def _evidence(record_key: str, issue: str, values: dict) -> dict:
    return {"record_key": record_key, "issue": issue, "values": values}


def _evaluate_rules(rules: list[QualityRule], rows: list[tuple[str, dict]],
                    total: int) -> tuple[dict, dict, list]:
    """返回 (每字段指标, 每字段阻断原因, 每字段证据样本)。"""
    metrics: dict[str, dict] = {}
    blocks: dict[str, list] = {}
    evidence: dict[str, list] = {}

    def ensure(name):
        metrics.setdefault(name, {
            "total": total, "present": 0, "missing": 0, "missing_rate": 0.0,
            "invalid": 0, "invalid_rate": 0.0, "duplicate": 0, "duplicate_rate": 0.0,
            "joint_pair": None, "ref_contradiction": None,
        })
        blocks.setdefault(name, [])
        evidence.setdefault(name, [])

    # 预计算每字段缺失/非空
    present_values: dict[str, list] = {}
    for rule in rules:
        ensure(rule.field_name)
    for rule in rules:
        name = rule.field_name
        vals = [(k, p.get(name)) for k, p in rows]
        missing = sum(1 for _, v in vals if _is_missing(v))
        m = metrics[name]
        m["missing"] = missing
        m["present"] = total - missing
        m["missing_rate"] = _rate(missing, total)
        present_values[name] = [(k, v) for k, v in vals if not _is_missing(v)]

    for rule in rules:
        name = rule.field_name
        p = rule.params or {}
        m = metrics[name]

        # ---- 缺失 ----
        if rule.rule_type == "missing":
            threshold = p.get("max_missing_rate", 0.0 if p.get("required") else 1.0)
            if m["missing_rate"] > threshold + 1e-12:
                reason = {
                    "rule_id": rule.id, "rule_type": "missing", "blocking": rule.blocking,
                    "message": (f"缺失率 {m['missing_rate']:.2%} 超过契约上限 "
                                f"{threshold:.2%}（缺失 {m['missing']}/{total}）"),
                }
                blocks[name].append(reason)
                if len(evidence[name]) < EVIDENCE_CAP:
                    for k, payload in rows:
                        if _is_missing(payload.get(name)) and len(evidence[name]) < EVIDENCE_CAP:
                            evidence[name].append(_evidence(
                                k, "字段缺失", {name: payload.get(name)}))

        # ---- 非法值 ----
        elif rule.rule_type == "invalid":
            bad = []
            for k, v in present_values.get(name, []):
                if "enum" in p and v not in p["enum"]:
                    bad.append((k, v, f"值 {v!r} 不在合法值域 {p['enum']}"))
                elif ("min" in p or "max" in p):
                    fv = _to_float(v)
                    if fv is None:
                        bad.append((k, v, f"值 {v!r} 不是数值"))
                    else:
                        if "min" in p and fv < p["min"]:
                            bad.append((k, v, f"值 {fv} 低于下限 {p['min']}"))
                        if "max" in p and fv > p["max"]:
                            bad.append((k, v, f"值 {fv} 高于上限 {p['max']}"))
                elif p.get("date_format"):
                    ok = isinstance(v, str)
                    if ok:
                        try:
                            datetime.strptime(v[:10], "%Y-%m-%d")
                        except ValueError:
                            ok = False
                    if not ok:
                        bad.append((k, v, f"值 {v!r} 不是合法日期(YYYY-MM-DD)"))
            m["invalid"] = len(bad)
            m["invalid_rate"] = _rate(len(bad), m["present"])
            threshold = p.get("max_invalid_rate", 0.0)
            if bad and m["invalid_rate"] > threshold + 1e-12:
                blocks[name].append({
                    "rule_id": rule.id, "rule_type": "invalid", "blocking": rule.blocking,
                    "message": (f"非法值率 {m['invalid_rate']:.2%} 超过上限 "
                                f"{threshold:.2%}（{len(bad)}/{m['present']}）"),
                })
                for k, v, msg in bad[:EVIDENCE_CAP]:
                    if len(evidence[name]) < EVIDENCE_CAP:
                        evidence[name].append(_evidence(k, "非法值", {name: v, "detail": msg}))

        # ---- 唯一性 ----
        elif rule.rule_type == "uniqueness":
            seen: dict = {}
            dup_keys: dict = {}
            for k, v in present_values.get(name, []):
                key = str(v)
                if key in seen:
                    dup_keys.setdefault(key, [seen[key]]).append(k)
                else:
                    seen[key] = k
            dup_records = sum(len(ks) for ks in dup_keys.values())
            m["duplicate"] = dup_records
            m["duplicate_rate"] = _rate(dup_records, m["present"])
            threshold = p.get("max_duplicate_rate", 0.0)
            if dup_records and m["duplicate_rate"] > threshold + 1e-12:
                blocks[name].append({
                    "rule_id": rule.id, "rule_type": "uniqueness", "blocking": rule.blocking,
                    "message": (f"重复率 {m['duplicate_rate']:.2%} 超过上限 "
                                f"{threshold:.2%}（{dup_records} 条非空记录重复）"),
                })
                for val, ks in list(dup_keys.items())[:EVIDENCE_CAP]:
                    if len(evidence[name]) < EVIDENCE_CAP:
                        evidence[name].append(_evidence(
                            ks[0], "唯一性破坏",
                            {name: val, "duplicate_record_keys": ks[:5]}))

        # ---- 跨字段一致性：成对出现（记录级联合比例） ----
        elif rule.rule_type == "consistency" and "pair_field" in p:
            pair = p["pair_field"]
            both = only_a = only_b = neither = 0
            break_samples = []
            for k, payload in rows:
                a_ok = not _is_missing(payload.get(name))
                b_ok = not _is_missing(payload.get(pair))
                if a_ok and b_ok:
                    both += 1
                elif a_ok and not b_ok:
                    only_a += 1
                    if len(break_samples) < EVIDENCE_CAP:
                        break_samples.append(_evidence(
                            k, f"成对字段一方缺失：{name} 存在但 {pair} 缺失",
                            {name: payload.get(name), pair: payload.get(pair)}))
                elif not a_ok and b_ok:
                    only_b += 1
                    if len(break_samples) < EVIDENCE_CAP:
                        break_samples.append(_evidence(
                            k, f"成对字段一方缺失：{pair} 存在但 {name} 缺失",
                            {name: payload.get(name), pair: payload.get(pair)}))
                else:
                    neither += 1
            joint = {
                "field": name, "pair_field": pair, "total": total,
                "both_present": both, "only_field_present": only_a,
                "only_pair_present": only_b, "both_missing": neither,
                "both_present_rate": _rate(both, total),
                "field_only_rate": _rate(only_a, total),
                "pair_only_rate": _rate(only_b, total),
                "both_missing_rate": _rate(neither, total),
                "pair_break_rate": _rate(only_a + only_b, total),
            }
            m["joint_pair"] = joint
            threshold = p.get("max_pair_break_rate", 0.0)
            if joint["pair_break_rate"] > threshold + 1e-12:
                msg = (f"记录级联合校验失败：{name} 与 {pair} 必须成对出现，"
                       f"联合比例 双全 {joint['both_present_rate']:.2%} / "
                       f"仅 {name} {joint['field_only_rate']:.2%} / "
                       f"仅 {pair} {joint['pair_only_rate']:.2%} / "
                       f"双缺 {joint['both_missing_rate']:.2%}，"
                       f"破坏率 {joint['pair_break_rate']:.2%} 超上限 {threshold:.2%}")
                blocks[name].append({
                    "rule_id": rule.id, "rule_type": "consistency",
                    "blocking": rule.blocking, "message": msg, "joint_with": pair})
                evidence[name].extend(break_samples[:EVIDENCE_CAP])

        # ---- 跨字段一致性：参考方法与结果范围 ----
        elif rule.rule_type == "consistency" and "ref_method_field" in p:
            method_field = p["ref_method_field"]
            ranges = p.get("ranges", {})
            evaluated = contradiction = 0
            samples = []
            for k, payload in rows:
                method = payload.get(method_field)
                raw = payload.get(name)
                if _is_missing(method) or _is_missing(raw):
                    continue
                evaluated += 1
                fv = _to_float(raw)
                if method not in ranges:
                    contradiction += 1
                    if len(samples) < EVIDENCE_CAP:
                        samples.append(_evidence(
                            k, "参考方法未登记合法结果范围",
                            {method_field: method, name: raw}))
                elif fv is None:
                    contradiction += 1
                    if len(samples) < EVIDENCE_CAP:
                        samples.append(_evidence(k, "结果值无法数值化", {name: raw}))
                else:
                    lo, hi = ranges[method]
                    if not (lo <= fv <= hi):
                        contradiction += 1
                        if len(samples) < EVIDENCE_CAP:
                            samples.append(_evidence(
                                k, f"参考方法 {method} 与结果范围矛盾（合法 {lo}~{hi}）",
                                {method_field: method, name: raw,
                                 "test_unit": payload.get("test_unit")}))
            m["ref_contradiction"] = {
                "method_field": method_field, "evaluated": evaluated,
                "contradiction": contradiction,
                "contradiction_rate": _rate(contradiction, evaluated),
                "ranges": ranges,
            }
            threshold = p.get("max_contradiction_rate", 0.0)
            if contradiction and _rate(contradiction, evaluated) > threshold + 1e-12:
                blocks[name].append({
                    "rule_id": rule.id, "rule_type": "consistency",
                    "blocking": rule.blocking,
                    "message": (f"参考方法-结果范围矛盾率 "
                                f"{_rate(contradiction, evaluated):.2%} 超上限 {threshold:.2%}"
                                f"（{contradiction}/{evaluated}）；计量单位本身合法不豁免该矛盾"),
                })
                evidence[name].extend(samples[:EVIDENCE_CAP])

    return metrics, blocks, evidence


# ----------------------------- 漂移评估 -----------------------------

def _evaluate_drift(db: Session, batch: DataBatch, field: ProductField,
                    rows: list[tuple[str, dict]]) -> tuple[str, dict]:
    name = field.field_name
    same_field = (
        db.query(DistributionBaseline)
        .filter(DistributionBaseline.product_id == batch.product_id,
                DistributionBaseline.partition_name == batch.partition_name,
                DistributionBaseline.field_name == name)
        .all()
    )
    # 字典版本不同：存在其他版本基线 → 版本不可比，绝不拼接新旧值域
    other_versions = [b for b in same_field if b.dict_version != batch.dict_version]
    baseline = next((b for b in same_field if b.dict_version == batch.dict_version), None)

    if baseline is None:
        if other_versions:
            b0 = other_versions[0]
            return "版本不可比", {
                "reason": "code_table_upgrade",
                "message": (f"字段字典/代码表版本变化：历史基线为 {b0.dict_version}，"
                            f"本批为 {batch.dict_version}，新旧值域不拼接计算漂移"),
                "baseline_dict_version": b0.dict_version,
                "current_dict_version": batch.dict_version,
            }
        # 无任何历史基线：本批样本不足以建立稳定基线时标证据不足，不推断无漂移
        current_n = sum(1 for _, p in rows if not _is_missing(p.get(name)))
        if current_n < MIN_STABLE_SAMPLE:
            return "证据不足", {
                "reason": "small_sample", "current_sample": current_n,
                "min_stable_sample": MIN_STABLE_SAMPLE,
                "message": (f"无历史基线且本批样本 n={current_n} 不足稳定阈值 "
                            f"{MIN_STABLE_SAMPLE}，不推断无漂移"),
            }
        return "未评估", {"reason": "no_baseline", "current_sample": current_n,
                          "message": "尚无同字典版本的历史合格基线，本批可作为首批候选基线"}

    detail = {"baseline_id": baseline.id, "baseline_sample": baseline.sample_size,
              "baseline_dict_version": baseline.dict_version,
              "min_stable_sample": baseline.min_stable_sample}

    # 标识类与日期类字段不做分布漂移（分别由唯一性/日期契约约束）
    if baseline.stats.get("kind") in ("identifier", "date"):
        return "未评估", {**detail, "reason": baseline.stats.get("kind"),
                          "message": "该字段类型以数据契约约束，不做分布漂移"}

    current_n = sum(1 for _, p in rows if not _is_missing(p.get(name)))
    # 任一侧样本不足 → 证据不足，不推断无漂移
    if baseline.sample_size < baseline.min_stable_sample or current_n < baseline.min_stable_sample:
        return "证据不足", {
            **detail, "reason": "small_sample", "current_sample": current_n,
            "message": (f"样本不足以形成稳定基线（基线 n={baseline.sample_size} / "
                        f"本批 n={current_n}，稳定阈值 {baseline.min_stable_sample}），"
                        "不推断无漂移"),
        }

    kind = _field_kind(field)
    cur_raw_values: list | None = None
    if kind == "numeric":
        cur_raw_values = [_to_float(v) for v in _field_values(field, rows)
                          if _to_float(v) is not None]
        cur_stats = _numeric_stats(cur_raw_values)
    else:
        cur_stats = _categorical_stats(
            [_category_value(field, v) for v in _field_values(field, rows)])

    # 数值字段：总体基线与季节基线分别用各自固定边界对当前原始值重分箱（PSI 才可比）
    overall = _drift_against(baseline.stats, cur_stats, cur_raw_values)
    detail["overall"] = overall
    season = _season_of(batch.window_from)
    seasonal_base = (baseline.seasonal_stats or {}).get(season)
    seasonal_metrics = None
    if seasonal_base and seasonal_base.get("n", 0) >= baseline.min_stable_sample:
        seasonal_metrics = _drift_against(seasonal_base, cur_stats, cur_raw_values)
        detail["seasonal"] = {"season": season, **seasonal_metrics}

    overall_drifted = bool(overall and overall["drifted"])
    if seasonal_metrics is not None:
        if overall_drifted and not seasonal_metrics["drifted"]:
            # 相对总体基线波动，但与同季节基线一致 → 合法季节漂移，不判漂移
            detail["message"] = (f"相对总体基线出现季节波动（{overall['method']} 超阈），"
                                 f"但与同季节（{season}）基线一致，判定为合法季节漂移")
            return "无漂移", detail
        if seasonal_metrics["drifted"]:
            detail["message"] = "分布漂移超出同季节基线区间，季节因素无法解释"
            return "漂移", detail
    if overall_drifted:
        detail["message"] = "分布漂移超出历史基线区间"
        return "漂移", detail
    detail["message"] = "分布落在历史基线（含同季节基线）区间内"
    return "无漂移", detail


# ----------------------------- 认证主流程 -----------------------------

def _grade(field_name: str, risk: str, blocking_failed: bool, observational_failed: bool,
           drift_status: str) -> str:
    if blocking_failed:
        return "C"
    if drift_status in ("证据不足", "版本不可比"):
        return "I"
    if drift_status == "漂移":
        return "C" if risk == "高" else "B"
    if observational_failed:
        return "B"
    return "A"


def certify_batch(db: Session, batch: DataBatch, trigger: str,
                  username: str, note: str = "",
                  establish_baseline: bool = False) -> QualityCertification:
    """对一个批次执行完整认证，生成新的认证版本（不改写任何源记录）。

    establish_baseline=True 用于"已确认合格的历史批次"基线建立：只跑契约、不做漂移
    判定（尚无基线可比较），其分布随后纳入后续批次的基线。
    """
    product = batch.product
    # 以历史合格批次（不含本批）重建同字典版本基线：保证漂移依据最新，且不引用自身
    for f in product.fields:
        rebuild_baseline(db, product.id, batch.partition_name, f.field_name,
                         batch.dict_version, exclude_batch_id=batch.id)
    db.flush()

    rules = (
        db.query(QualityRule)
        .filter(QualityRule.product_id == product.id, QualityRule.enabled == True)  # noqa: E712
        .filter(sa.or_(QualityRule.dict_version.is_(None),
                       QualityRule.dict_version == batch.dict_version))
        .order_by(QualityRule.id)
        .all()
    )
    rule_version = max((r.rule_version for r in rules), default=1)
    rows = [(r.record_key, r.payload) for r in batch.records]
    total = len(rows)
    if total == 0:
        raise QualityError("批次无源记录，无法认证")

    metrics, blocks, evidence = _evaluate_rules(rules, rows, total)

    # 字段字典内的每个字段都产出结果（即使没有契约规则）
    dict_fields = {f.field_name: f for f in product.fields}
    for name in dict_fields:
        metrics.setdefault(name, {
            "total": total,
            "present": sum(1 for _, p in rows if not _is_missing(p.get(name))),
            "missing": sum(1 for _, p in rows if _is_missing(p.get(name))),
            "missing_rate": 0.0, "invalid": 0, "invalid_rate": 0.0,
            "duplicate": 0, "duplicate_rate": 0.0,
            "joint_pair": None, "ref_contradiction": None})
        m = metrics[name]
        m["missing_rate"] = _rate(m["missing"], total)
        blocks.setdefault(name, [])
        evidence.setdefault(name, [])

    # 成对关系破坏传播：伙伴字段不能单独"通过"掩盖关系破坏；证据一并复制，保证各自可追溯
    for rule in rules:
        if rule.rule_type == "consistency" and "pair_field" in rule.params:
            pair = rule.params["pair_field"]
            if any(b.get("rule_id") == rule.id for b in blocks.get(rule.field_name, [])):
                joint_msg = next(b["message"] for b in blocks[rule.field_name]
                                 if b.get("rule_id") == rule.id)
                blocks.setdefault(pair, []).append({
                    "rule_id": rule.id, "rule_type": "consistency",
                    "blocking": rule.blocking, "joint_with": rule.field_name,
                    "message": f"关联阻断：{joint_msg}",
                })
                existing_keys = {e["record_key"] for e in evidence.setdefault(pair, [])}
                for e in evidence.get(rule.field_name, []):
                    if e["record_key"] not in existing_keys and len(evidence[pair]) < EVIDENCE_CAP:
                        evidence[pair].append(e)
                        existing_keys.add(e["record_key"])

    rule_refs = {}
    risk_of = {}
    for r in rules:
        rule_refs.setdefault(r.field_name, []).append(
            {"rule_id": r.id, "rule_type": r.rule_type,
             "rule_version": r.rule_version, "blocking": r.blocking})
        risk_of[r.field_name] = r.risk_level

    prev_version = max((c.version for c in batch.certifications), default=0)
    certification = QualityCertification(
        batch_id=batch.id, version=prev_version + 1, rule_version=rule_version,
        trigger=trigger, created_by=username, summary=note)

    # 先在内存中算完所有字段评级与认证结论，再统一持久化——
    # 避免认证对象在 decision 等非空列赋值前被 autoflush 提前 INSERT。
    grade_buckets = {"A": [], "B": [], "C": [], "I": []}
    result_payloads: list[dict] = []
    for name, field in dict_fields.items():
        field_blocks = blocks.get(name, [])
        blocking_failed = any(b.get("blocking") for b in field_blocks)
        observational_failed = any(not b.get("blocking") for b in field_blocks)
        if establish_baseline:
            drift_status, drift_detail = "未评估", {
                "reason": "baseline_seed",
                "message": "基线建立批次（已确认合格的历史批次），不参与漂移判定"}
        else:
            drift_status, drift_detail = _evaluate_drift(db, batch, field, rows)
        risk = risk_of.get(name, "中")
        grade = _grade(name, risk, blocking_failed, observational_failed, drift_status)
        grade_buckets[grade].append(name)
        result_payloads.append({
            "field_name": name, "partition_name": batch.partition_name,
            "dict_version": batch.dict_version,
            "sample_size": metrics[name]["present"], "fitness_grade": grade,
            "contract_passed": not field_blocks, "drift_status": drift_status,
            "metrics": metrics[name], "drift_detail": drift_detail,
            "block_reasons": field_blocks,
            "evidence_samples": evidence.get(name, [])[:EVIDENCE_CAP],
            "rule_refs": rule_refs.get(name, []),
        })

    field_count = len(dict_fields)
    blocked = len(grade_buckets["C"])
    insufficient = len(grade_buckets["I"])
    passed = field_count - blocked - insufficient
    if blocked:
        decision = "不通过"
    elif insufficient:
        decision = "证据不足"
    elif grade_buckets["B"]:
        decision = "有条件通过"
    else:
        decision = "通过"

    certification.decision = decision
    certification.field_count = field_count
    certification.passed_fields = passed
    certification.blocked_fields = blocked
    certification.insufficient_fields = insufficient
    certification.pass_rate = round(passed / field_count, 6) if field_count else 0.0
    certification.research_fitness = {
        "confirmatory": sorted(grade_buckets["A"]),
        "exploratory": sorted(grade_buckets["A"] + grade_buckets["B"]),
        "unusable": sorted(grade_buckets["C"]),
        "insufficient": sorted(grade_buckets["I"]),
        "grade_labels": FITNESS_LABELS,
        "note": "关键字段（高风险）未达 A 时不得以总体通过率放行；C 级字段禁止进入研究数据集",
    }
    certification.summary = note or (
        f"规则版本 v{rule_version}：{decision}，字段通过比例 "
        f"{passed}/{field_count}，阻断 {blocked}，证据不足 {insufficient}")

    # 认证对象字段齐备后再入库，随后写入字段级结果
    db.add(certification)
    db.flush()
    for payload in result_payloads:
        db.add(FieldQualityResult(certification_id=certification.id, **payload))

    batch.status = "已更正" if trigger == "批次更正" else "已认证"
    db.flush()
    return certification


def new_batch_no() -> str:
    return "DQ" + uuid.uuid4().hex[:12].upper()
