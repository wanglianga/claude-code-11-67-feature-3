"""验收测试：字段交集、资格边界、伦理失效批次、并发额度占用、重复事件、访问依据回查。"""
import threading
import uuid

from tests.conftest import login


# ---------- 工具 ----------

def _ids(client, headers):
    products = {p["code"]: p["id"] for p in client.get("/api/catalog/products", headers=headers).json()}
    projects = {p["code"]: p["id"] for p in client.get("/api/projects", headers=headers).json()}
    return products, projects


def _qual(client, headers, project_id, product_id, purpose):
    items = client.get(
        f"/api/qualifications?project_id={project_id}&status=已签发", headers=headers
    ).json()
    match = [q for q in items if q["product_id"] == product_id and q["purpose_code"] == purpose]
    assert match, f"资格不存在: project={project_id} product={product_id} purpose={purpose}"
    return client.get(f"/api/qualifications/{match[0]['id']}", headers=headers).json()


def _access(client, headers, project_id, product_id, purpose, kind="查询",
            fields=None, request_id=None, export_rows=100):
    payload = {
        "project_id": project_id, "product_id": product_id, "purpose_code": purpose,
        "kind": kind, "requested_fields": fields or [],
        "request_id": request_id or uuid.uuid4().hex, "export_rows": export_rows,
    }
    return client.post("/api/access/query", json=payload, headers=headers).json()


# ---------- 1. 字段交集 ----------

def test_field_intersection(client):
    admin = login(client, "admin", "admin123")
    products, projects = _ids(client, admin)

    # TRAIN（L3 上限，禁直接标识符）：剔除 patient_name(L4)，其余 8 个放行
    q = _qual(client, admin, projects["PRJ-A"], products["P-LAB"], "TRAIN")
    names = {f["field_name"] for f in q["field_projection"]}
    assert names == {"subject_code", "test_item", "test_result", "test_unit",
                     "test_date", "age_at_test", "abnormal_flag", "ref_method"}
    # test_result 可用期止于 2026-12-31，窗口应被字段可用期裁剪
    tr = next(f for f in q["field_projection"] if f["field_name"] == "test_result")
    assert tr["window_to"] == "2026-12-31"
    assert tr["window_from"] <= tr["window_to"]

    # PUBLISH（L2 上限，禁直接标识符+准标识符）：只剩 6 个低敏字段
    q2 = _qual(client, admin, projects["PRJ-A"], products["P-LAB"], "PUBLISH")
    names2 = {f["field_name"] for f in q2["field_projection"]}
    assert names2 == {"subject_code", "test_item", "test_unit", "age_at_test",
                      "abnormal_flag", "ref_method"}
    # 资格依据完整记录伦理与用途条件
    assert q2["basis"]["ethics"][0]["approval_no"] == "EA-2025-001"
    assert q2["basis"]["effective_max_sensitivity"] == 2
    assert {e["field_name"] for e in q2["basis"]["excluded_fields"]} >= {
        "patient_name", "test_result", "test_date"}


# ---------- 2. 资格边界：跨课题不扩权、多用途不取并集 ----------

def test_cross_project_and_purpose_boundary(client):
    zm = login(client, "zhangmin", "zhang123")
    admin = login(client, "admin", "admin123")
    products, projects = _ids(client, admin)

    # 张敏在 PRJ-B 没有 P-LAB 资格 —— 即使她在 PRJ-A 有 TRAIN 资格也不得借用
    r = _access(client, zm, projects["PRJ-B"], products["P-LAB"], "TRAIN")
    assert r["event"]["status"] == "拒绝"
    assert "无" in r["event"]["deny_reason"] and "资格" in r["event"]["deny_reason"]

    # 张敏在 PRJ-B 用 EXTRACT 访问 P-IMG：只含 B 的投影（7 字段，无 L4）
    r = _access(client, zm, projects["PRJ-B"], products["P-IMG"], "EXTRACT")
    ev = r["event"]
    assert ev["status"] == "成功"
    granted = {f["field_name"] for f in ev["granted_fields"]}
    assert granted == {"exam_id", "subject_code", "modality", "body_part",
                       "exam_date", "image_abstract", "report_text"}
    assert "patient_name" not in granted and "patient_id_card" not in granted

    # 同一成员在 PRJ-A 用 PUBLISH（窄用途）：不得并入 TRAIN 的 L3 字段
    r = _access(client, zm, projects["PRJ-A"], products["P-LAB"], "PUBLISH")
    granted = {f["field_name"] for f in r["event"]["granted_fields"]}
    assert granted == {"subject_code", "test_item", "test_unit",
                       "age_at_test", "abnormal_flag", "ref_method"}
    assert "test_result" not in granted  # TRAIN 才有的字段不能借并集扩大

    # 显式申请投影外字段 → 拒绝
    r = _access(client, zm, projects["PRJ-A"], products["P-LAB"], "TRAIN",
                fields=["patient_name"])
    assert r["event"]["status"] == "拒绝"
    assert "投影" in r["event"]["deny_reason"]

    # 申请部分在投影内：只放行交集，越界字段列入 rejected_fields
    r = _access(client, zm, projects["PRJ-A"], products["P-LAB"], "TRAIN",
                fields=["test_result", "patient_name"])
    ev = r["event"]
    assert ev["status"] == "成功"
    assert [f["field_name"] for f in ev["granted_fields"]] == ["test_result"]
    assert ev["quota_snapshot"]["rejected_fields"] == ["patient_name"]


def test_export_rules(client):
    admin = login(client, "admin", "admin123")
    products, projects = _ids(client, admin)
    zm = login(client, "zhangmin", "zhang123")
    zl = login(client, "zhaolei", "zhao123")
    pi = login(client, "wangjianguo", "wang123")

    # PUBLISH 用途不允许导出
    r = _access(client, zm, projects["PRJ-A"], products["P-LAB"], "PUBLISH", kind="导出")
    assert r["event"]["status"] == "拒绝" and "不允许导出" in r["event"]["deny_reason"]
    # 统计师角色无导出权限（即使用途允许）
    r = _access(client, zl, projects["PRJ-A"], products["P-LAB"], "TRAIN", kind="导出")
    assert r["event"]["status"] == "拒绝" and "角色" in r["event"]["deny_reason"]
    # PI 在 TRAIN 用途可导出，扣导出行数额度
    before = client.get("/api/quota/accounts", headers=admin).json()
    used_before = next(a for a in before if a["project_id"] == projects["PRJ-A"])["used_export_rows"]
    r = _access(client, pi, projects["PRJ-A"], products["P-LAB"], "TRAIN",
                kind="导出", export_rows=300)
    assert r["event"]["status"] == "成功"
    after = client.get("/api/quota/accounts", headers=admin).json()
    used_after = next(a for a in after if a["project_id"] == projects["PRJ-A"])["used_export_rows"]
    assert used_after - used_before == 300


# ---------- 3. 伦理失效批次：未完成不得签发、已完成独立状态、不假报成功 ----------

def test_ethics_invalid_batch_partial(client):
    admin = login(client, "admin", "admin123")
    products, projects = _ids(client, admin)

    resp = client.post("/api/qualifications/batches", headers=admin, json={
        "title": "混合批次（含已失效伦理课题）",
        "items": [
            {"project_id": projects["PRJ-A"], "product_id": products["P-FU"], "purpose_code": "TRAIN"},
            {"project_id": projects["PRJ-C"], "product_id": products["P-LAB"], "purpose_code": "REVIEW"},
            {"project_id": projects["PRJ-C"], "product_id": products["P-IMG"], "purpose_code": "REVIEW"},
        ],
    })
    assert resp.status_code == 200
    batch = resp.json()
    assert batch["status"] == "部分完成"  # 绝不整体假报成功
    assert batch["succeeded"] == 1 and batch["failed"] == 2
    by_key = {(i["project_id"], i["product_id"]): i for i in batch["items"]}
    assert by_key[(projects["PRJ-A"], products["P-FU"])]["status"] == "已签发"
    c_items = [i for i in batch["items"] if i["project_id"] == projects["PRJ-C"]]
    assert all(i["status"] == "签发失败" for i in c_items)
    assert all("伦理" in i["fail_reason"] for i in c_items)

    # 全部为失效伦理 → 批次失败
    resp = client.post("/api/qualifications/batches", headers=admin, json={
        "title": "纯失效批次",
        "items": [{"project_id": projects["PRJ-C"], "product_id": products["P-BIO"],
                   "purpose_code": "REVIEW"}],
    })
    assert resp.json()["status"] == "失败"

    # 批次处理中伦理失效：先撤回 PRJ-A 批件，再开通 → 不得签发
    detail = client.get(f"/api/projects/{projects['PRJ-A']}", headers=admin).json()
    ethics_id = detail["ethics"][0]["id"]
    client.post(f"/api/projects/{projects['PRJ-A']}/ethics/{ethics_id}/revoke",
                headers=admin, json={"reason": "委员会年度审查未通过"})
    resp = client.post("/api/qualifications/batches", headers=admin, json={
        "title": "伦理失效后开通",
        "items": [{"project_id": projects["PRJ-A"], "product_id": products["P-BIO"],
                   "purpose_code": "TRAIN"}],
    })
    batch = resp.json()
    assert batch["status"] == "失败"
    assert batch["items"][0]["status"] == "签发失败"
    assert "伦理" in batch["items"][0]["fail_reason"]
    # 恢复批件供后续用例使用
    client.post(f"/api/projects/{projects['PRJ-A']}/ethics/{ethics_id}/restore", headers=admin)

    # 重复开通同一三元组 → 签发失败（须先撤回）
    resp = client.post("/api/qualifications/batches", headers=admin, json={
        "title": "重复开通",
        "items": [{"project_id": projects["PRJ-A"], "product_id": products["P-LAB"],
                   "purpose_code": "TRAIN"}],
    })
    item = resp.json()["items"][0]
    assert item["status"] == "签发失败" and "已存在" in item["fail_reason"]


# ---------- 4. 并发额度占用 ----------

def test_concurrent_reservation_limit(client):
    admin = login(client, "admin", "admin123")
    _, projects = _ids(client, admin)
    prj_b = projects["PRJ-B"]  # max_concurrent = 2

    results = []

    def acquire():
        resp = client.post("/api/quota/reservations", headers=admin,
                           json={"project_id": prj_b, "kind": "查询"})
        results.append(resp.status_code)

    threads = [threading.Thread(target=acquire) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(200) == 2, f"应恰好 2 个占用成功，实际 {results}"
    assert results.count(409) == 3

    # 占用中数量 = 2；释放一个后可再占用
    accounts = client.get("/api/quota/accounts", headers=admin).json()
    acc_b = next(a for a in accounts if a["project_id"] == prj_b)
    assert acc_b["active_reservations"] == 2
    rid = client.get("/api/quota/reservations?status=占用中", headers=admin).json()[0]["id"]
    client.post(f"/api/quota/reservations/{rid}/release", headers=admin)
    resp = client.post("/api/quota/reservations", headers=admin,
                       json={"project_id": prj_b, "kind": "查询"})
    assert resp.status_code == 200


def test_service_level_row_lock(client):
    """服务层多线程直测：行锁下占用数绝不超过上限。"""
    from app.db import SessionLocal
    from app.models import Project
    from app.services import quota as quota_svc

    db = SessionLocal()
    prj_b = db.query(Project).filter(Project.code == "PRJ-B").one().id
    db.close()
    ok, fail = [], []

    def worker():
        s = SessionLocal()
        try:
            quota_svc.acquire(s, prj_b, "查询")
            s.commit()
            ok.append(1)
        except quota_svc.QuotaError:
            s.rollback()
            fail.append(1)
        finally:
            s.close()

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 2 and len(fail) == 4


# ---------- 5. 重复事件：额度只扣一次、重复回执可查 ----------

def test_duplicate_usage_report_idempotent(client):
    admin = login(client, "admin", "admin123")
    _, projects = _ids(client, admin)
    prj_a = projects["PRJ-A"]
    key = "compute-job-" + uuid.uuid4().hex[:8]

    r1 = client.post("/api/quota/usage", headers=admin, json={
        "project_id": prj_a, "kind": "机时", "amount": 2.5, "idempotency_key": key})
    assert r1.status_code == 200 and r1.json()["duplicate"] is False
    # 断线重试：同一幂等键再次上报
    r2 = client.post("/api/quota/usage", headers=admin, json={
        "project_id": prj_a, "kind": "机时", "amount": 2.5, "idempotency_key": key})
    assert r2.status_code == 200 and r2.json()["duplicate"] is True
    assert r2.json()["event"]["receipt_no"] == r1.json()["event"]["receipt_no"]

    # 额度只扣一次
    accounts = client.get("/api/quota/accounts", headers=admin).json()
    acc = next(a for a in accounts if a["project_id"] == prj_a)
    assert acc["used_compute_hours"] == 2.5

    # 重复回执可查：1 次首次 + 1 次重复
    receipts = client.get(f"/api/quota/usage/by-key/{key}/receipts", headers=admin).json()
    assert receipts["deducted_once"] is True
    assert len(receipts["reports"]) == 2
    assert [r["is_duplicate"] for r in receipts["reports"]] == [False, True]


def test_access_retry_idempotent(client):
    zm = login(client, "zhangmin", "zhang123")
    admin = login(client, "admin", "admin123")
    products, projects = _ids(client, admin)
    rid = "retry-" + uuid.uuid4().hex[:8]

    r1 = _access(client, zm, projects["PRJ-A"], products["P-LAB"], "TRAIN", request_id=rid)
    r2 = _access(client, zm, projects["PRJ-A"], products["P-LAB"], "TRAIN", request_id=rid)
    assert r1["event"]["status"] == "成功"
    assert r2["idempotent_replay"] is True
    assert r2["event"]["id"] == r1["event"]["id"]

    # 查询额度只扣一次（种子示范访问已用 1，本次 +1 = 2）
    accounts = client.get("/api/quota/accounts", headers=admin).json()
    acc = next(a for a in accounts if a["project_id"] == projects["PRJ-A"])
    assert acc["used_query"] == 2


def test_quota_exhaustion(client):
    admin = login(client, "admin", "admin123")
    _, projects = _ids(client, admin)
    prj_b = projects["PRJ-B"]  # 机时预算 50
    k1 = "exhaust-" + uuid.uuid4().hex[:6]
    r = client.post("/api/quota/usage", headers=admin, json={
        "project_id": prj_b, "kind": "机时", "amount": 50, "idempotency_key": k1})
    assert r.status_code == 200
    r = client.post("/api/quota/usage", headers=admin, json={
        "project_id": prj_b, "kind": "机时", "amount": 0.5,
        "idempotency_key": "exhaust-" + uuid.uuid4().hex[:6]})
    assert r.status_code == 409 and "机时额度不足" in r.json()["detail"]


# ---------- 6. 访问依据回查 ----------

def test_audit_reconstruction(client):
    auditor = login(client, "auditor", "audit123")
    admin = login(client, "admin", "admin123")
    zm = login(client, "zhangmin", "zhang123")

    events = client.get("/api/access/events", headers=auditor).json()
    seed_event = next(e for e in events if e["request_id"] == "seed-demo-0001")
    audit = client.get(f"/api/audit/access/{seed_event['id']}", headers=auditor).json()

    # 当时的产品定义
    then = audit["product_then"]
    assert then["code"] == "P-LAB" and len(then["fields"]) == 9
    # 当时的资格依据
    basis = audit["qualification_basis_then"]
    assert basis["basis"]["ethics"][0]["approval_no"] == "EA-2025-001"
    assert basis["purpose_code"] == "TRAIN"
    assert {f["field_name"] for f in basis["field_projection"]} == {
        "subject_code", "test_item", "test_result", "test_unit",
        "test_date", "age_at_test", "abnormal_flag", "ref_method"}
    # 当时的额度变化
    trail = audit["quota_trail"]
    assert trail["usage_event"]["receipt_no"]
    assert trail["reservation"]["status"] == "已结算"
    assert trail["usage_event"]["balance_after"]["used_query"] == 1

    # 目录变更后，审计可对比"当时 vs 现在"
    products = client.get("/api/catalog/products", headers=admin).json()
    p_lab = next(p for p in products if p["code"] == "P-LAB")
    detail = client.get(f"/api/catalog/products/{p_lab['id']}", headers=admin).json()
    tr_field = next(f for f in detail["fields"] if f["field_name"] == "test_result")
    client.put(f"/api/catalog/products/{p_lab['id']}/fields/{tr_field['id']}",
               headers=admin, json={"sensitivity_level": 4})
    audit2 = client.get(f"/api/audit/access/{seed_event['id']}", headers=auditor).json()
    assert any(d["field_name"] == "test_result" and "L3 → L4" in d["change"]
               for d in audit2["catalog_diff"])
    # 当时的快照不受目录变更影响
    still_then = next(f for f in audit2["product_then"]["fields"]
                      if f["field_name"] == "test_result")
    assert still_then["sensitivity_level"] == 3

    # 业务角色无权审计
    resp = client.get(f"/api/audit/access/{seed_event['id']}", headers=zm)
    assert resp.status_code == 403


def test_health_and_auth(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/catalog/products").status_code == 401
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
