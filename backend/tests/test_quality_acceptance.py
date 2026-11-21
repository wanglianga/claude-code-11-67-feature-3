"""批次质量认证验收：五类样例逐字段结果与证据追查、记录级联合比例、
代码表版本隔离、合法季节漂移、小样本证据不足、认证版本化与源记录不可变。"""
import uuid

from tests.conftest import login


def _batches(client, headers):
    return {b["batch_no"]: b for b in client.get("/api/quality/batches", headers=headers).json()}


def _cert_of(client, headers, batch_no):
    b = _batches(client, headers)[batch_no]
    certs = client.get(f"/api/quality/certifications?batch_id={b['id']}",
                       headers=headers).json()
    latest = certs[0]  # 版本倒序
    return b, client.get(f"/api/quality/certifications/{latest['id']}",
                         headers=headers).json()


def _field(cert, name):
    return next(r for r in cert["field_results"] if r["field_name"] == name)


# ---------- 1. 缺失字段 / 非法值 / 参考方法-结果范围矛盾 ----------

def test_missing_illegal_and_ref_contradiction(client):
    admin = login(client, "admin", "admin123")
    _, cert = _cert_of(client, admin, "DQ-CUR-LAB-MISSING")

    assert cert["decision"] == "不通过"
    # 总体通过率不能放行关键字段：test_result 为高风险关键字段，单列 C
    tr = _field(cert, "test_result")
    assert tr["fitness_grade"] == "C"
    assert tr["metrics"]["missing"] == 8 and tr["metrics"]["missing_rate"] == 0.2
    rc = tr["metrics"]["ref_contradiction"]
    assert rc["contradiction"] == 3  # 超范围 2 条 + 超上限 150 一条
    # 计量单位合法（mmol/L）不豁免参考方法矛盾——阻断原因明确写出
    assert any("参考方法" in x["message"] for x in tr["block_reasons"])

    sc = _field(cert, "subject_code")
    assert sc["fitness_grade"] == "C" and sc["metrics"]["missing"] == 3
    af = _field(cert, "abnormal_flag")
    assert af["fitness_grade"] == "C" and af["metrics"]["invalid"] == 2

    # 证据样本可回溯到源记录原样数据
    assert tr["evidence_samples"], "关键字段必须留存证据样本"
    key = tr["evidence_samples"][0]["record_key"]
    batch_id = cert["batch"]["id"]
    rec = client.get(f"/api/quality/batches/{batch_id}/records/by-key/{key}",
                     headers=admin).json()
    assert rec["record_key"] == key and "payload" in rec
    # 研究用途分级：C 级字段禁止进入任何研究数据集
    assert "test_result" in cert["research_fitness"]["unusable"]
    assert "test_result" not in cert["research_fitness"]["confirmatory"]


# ---------- 2. 成对字段记录级联合比例，分别"通过"不得掩盖关系破坏 ----------

def test_pair_field_joint_ratio(client):
    admin = login(client, "admin", "admin123")
    _, cert = _cert_of(client, admin, "DQ-CUR-IMG-PAIR")
    assert cert["decision"] == "不通过"

    ed = _field(cert, "exam_date")
    ia = _field(cert, "image_abstract")
    joint = ed["metrics"]["joint_pair"]
    # 记录级联合比例四象限完整报告
    assert joint["both_present"] == 30 and joint["only_field_present"] == 10
    assert joint["both_present_rate"] == 0.75 and joint["pair_break_rate"] == 0.25
    # 关系破坏同时阻断两个字段，image_abstract 不能因自身非空而单独通过
    assert ed["fitness_grade"] == "C" and ia["fitness_grade"] == "C"
    assert any(x.get("joint_with") == "exam_date" for x in ia["block_reasons"])
    # 两侧都带证据且可回溯
    assert ed["evidence_samples"] and ia["evidence_samples"]


# ---------- 3. 合法季节漂移：同季节基线可解释，不判漂移 ----------

def test_legitimate_seasonal_drift(client):
    admin = login(client, "admin", "admin123")
    _, cert = _cert_of(client, admin, "DQ-CUR-LAB-SEASON")
    tr = _field(cert, "test_result")
    # 相对总体基线超阈，但同季节基线一致 → 合法季节漂移，字段仍为 A
    assert tr["drift_status"] == "无漂移"
    assert tr["fitness_grade"] == "A"
    assert "合法季节漂移" in tr["drift_detail"]["message"]
    assert cert["decision"] == "通过"
    # 对照批次同样为全 A
    _, ok_cert = _cert_of(client, admin, "DQ-CUR-LAB-OK")
    assert ok_cert["decision"] == "通过"


# ---------- 4. 代码表升级：新旧值域不拼接漂移 ----------

def test_code_table_upgrade_not_concatenated(client):
    admin = login(client, "admin", "admin123")
    b, cert = _cert_of(client, admin, "DQ-CUR-LAB-DICT-V2")
    assert b["dict_version"] == "DICT-2026.1"
    # 所有字段：存在 v1 基线但版本不同 → 版本不可比，绝不拼接计算漂移
    assert all(r["drift_status"] == "版本不可比" for r in cert["field_results"])
    rm = _field(cert, "ref_method")
    assert rm["drift_detail"]["reason"] == "code_table_upgrade"
    assert rm["drift_detail"]["baseline_dict_version"] == "DICT-2024.2"
    # 契约层面：v1 的酶法/免疫法枚举规则不再套用，二代新代码不被判非法
    assert rm["contract_passed"] is True
    assert cert["decision"] == "证据不足"

    # 基线按字典版本隔离：v1 基线仍在，且没有 v2 拼接行
    baselines = client.get(
        f"/api/quality/baselines?product_id={b['product_id']}&field_name=ref_method",
        headers=admin).json()
    versions = {x["dict_version"] for x in baselines}
    assert "DICT-2024.2" in versions and "DICT-2026.1" not in versions


# ---------- 5. 小样本分区：证据不足，不推断无漂移 ----------

def test_small_sample_insufficient(client):
    admin = login(client, "admin", "admin123")
    b, cert = _cert_of(client, admin, "DQ-CUR-LAB-RARE")
    assert b["record_count"] == 8
    assert cert["decision"] == "证据不足"
    assert all(r["fitness_grade"] == "I" for r in cert["field_results"])
    tr = _field(cert, "test_result")
    assert tr["drift_status"] == "证据不足"
    assert "不推断无漂移" in tr["drift_detail"]["message"]
    # 证据不足字段不得进入确认性研究字段集
    assert cert["research_fitness"]["confirmatory"] == []


# ---------- 6. 规则调整 → 重认证生成新版本，旧认证保留 ----------

def test_rule_adjust_recertify_versions(client):
    admin = login(client, "admin", "admin123")
    b, v1 = _cert_of(client, admin, "DQ-CUR-LAB-OK")
    assert v1["version"] == 1 and v1["decision"] == "通过"

    # 新增一条阻断型严格规则（test_item 只允许一个不存在的项目）
    resp = client.post("/api/quality/rules", headers=admin, json={
        "product_id": b["product_id"], "field_name": "test_item",
        "rule_type": "invalid", "params": {"enum": ["不存在的检验项目"]},
        "blocking": True, "risk_level": "高"})
    assert resp.status_code == 200

    recert = client.post(f"/api/quality/batches/{b['id']}/recertify",
                         headers=admin, json={"trigger": "规则调整",
                                              "note": "收紧检验项目契约"}).json()
    assert recert["version"] == 2 and recert["decision"] == "不通过"
    assert recert["rule_version"] >= v1["rule_version"]
    ti = _field(recert, "test_item")
    assert ti["fitness_grade"] == "C" and ti["metrics"]["invalid_rate"] == 1.0

    # 旧认证版本完整保留且结论不变
    old = client.get(f"/api/quality/certifications/{v1['id']}", headers=admin).json()
    assert old["version"] == 1 and old["decision"] == "通过"
    versions = client.get(f"/api/quality/certifications?batch_id={b['id']}",
                          headers=admin).json()
    assert {x["version"] for x in versions} == {1, 2}


# ---------- 7. 批次更正：新建批次，旧批次/旧认证保留 ----------

def test_batch_correction_keeps_history(client):
    admin = login(client, "admin", "admin123")
    original, bad_cert = _cert_of(client, admin, "DQ-CUR-LAB-MISSING")
    assert bad_cert["decision"] == "不通过"

    good_rows = client.get(
        f"/api/quality/batches/{original['id']}/records?limit=5",
        headers=admin).json()["records"]
    corrected = [{
        "record_key": f"FIX-{r['record_key']}",
        "payload": {**r["payload"],
                    "test_result": r["payload"].get("test_result") or 5.5,
                    "subject_code": r["payload"].get("subject_code") or f"FIX-{uuid.uuid4().hex[:6]}",
                    "abnormal_flag": "正常" if r["payload"].get("abnormal_flag") in
                    ("未知", "异常++") else r["payload"].get("abnormal_flag")},
    } for r in good_rows]
    resp = client.post(f"/api/quality/batches/{original['id']}/correction",
                       headers=admin, json={
        "product_id": original["product_id"], "center_code": original["center_code"],
        "partition_name": original["partition_name"],
        "dict_version": original["dict_version"],
        "window_from": original["window_from"], "window_to": original["window_to"],
        "note": "补齐缺失并修正非法值", "records": corrected})
    assert resp.status_code == 200
    data = resp.json()
    new_b = data["batch"]
    assert original["batch_no"] in new_b["note"] and new_b["id"] != original["id"]
    # 更正批次生成独立认证版本，触发标记固定为「批次更正」，源记录为更正后的新数据
    assert data["certification"]["trigger"] == "批次更正"
    assert data["certification"]["version"] == 1
    fixed = client.get(
        f"/api/quality/batches/{new_b['id']}/records/by-key/{corrected[0]['record_key']}",
        headers=admin).json()
    assert fixed["payload"]["test_result"] == corrected[0]["payload"]["test_result"]

    # 原批次与其不通过认证仍可查
    still = client.get(f"/api/quality/batches/{original['id']}", headers=admin).json()
    assert still["latest_decision"] == "不通过"


# ---------- 8. 源记录只读不可变 + 权限 ----------

def test_source_records_immutable_and_permissions(client):
    admin = login(client, "admin", "admin123")
    analyst = login(client, "zhangmin", "zhang123")
    b, _ = _cert_of(client, admin, "DQ-CUR-LAB-OK")

    # 源记录只有 GET，没有改写端点
    assert client.put(f"/api/quality/batches/{b['id']}/records",
                      headers=admin, json={}).status_code == 405
    assert client.delete(
        f"/api/quality/batches/{b['id']}/records/by-key/x",
        headers=admin).status_code == 405

    # 业务角色只读：可查询，不能入库批次/维护规则
    assert client.get("/api/quality/batches", headers=analyst).status_code == 200
    assert client.post("/api/quality/batches", headers=analyst, json={}).status_code == 403
    assert client.post("/api/quality/rules", headers=analyst, json={}).status_code == 403


# ---------- 9. API 入库即认证：端到端新批次 ----------

def test_api_batch_ingest_and_certify(client):
    admin = login(client, "admin", "admin123")
    products = {p["code"]: p["id"]
                for p in client.get("/api/catalog/products", headers=admin).json()}
    records = [{"record_key": f"K{i}", "payload": {
        "subject_code": f"API{i:05d}", "patient_name": f"患者{i}",
        "test_item": "血糖", "test_result": 5.0 + (i % 5) * 0.4,
        "test_unit": "mmol/L", "test_date": "2026-10-01",
        "age_at_test": 40 + i, "abnormal_flag": "正常", "ref_method": "酶法"}}
        for i in range(35)]
    resp = client.post("/api/quality/batches", headers=admin, json={
        "product_id": products["P-LAB"], "center_code": "CHC-01 总院",
        "partition_name": "检验常规分区", "dict_version": "DICT-2024.2",
        "window_from": "2026-10-01", "window_to": "2026-10-20",
        "note": "API 端到端批次", "records": records})
    assert resp.status_code == 200
    data = resp.json()
    assert data["certification"]["version"] == 1
    assert data["batch"]["record_count"] == 35
    # 入库的源记录与提交完全一致（未被改写）
    got = client.get(
        f"/api/quality/batches/{data['batch']['id']}/records/by-key/K0",
        headers=admin).json()
    assert got["payload"] == records[0]["payload"]
