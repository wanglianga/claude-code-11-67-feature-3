# 科研数据产品目录与项目资格开通工作台

面向医学研究中心的数据治理系统：在正式开通前回答三个问题——**能用哪些字段**（产品字段 × 用途条件 × 成员范围 × 伦理约束求交）、**字段在所需时间范围内是否可用**（字段可用期 ∩ 资格有效期）、**计算额度是否适配**（预算 / 并发占用 / 实际消耗账本），并对每一次数据访问可还原当时的产品定义、资格依据与额度变化。

在此之上新增**数据产品批次质量认证**：数据产品目录只说明字段定义与来源，不能证明某一批实际数据满足研究使用要求。系统对每批到数数据按字段做硬性契约校验（缺失 / 非法值 / 唯一性 / 跨字段一致性）并与历史合格批次比较分布漂移，输出按字段/分区的适用等级、阻断原因、可供的研究目的与可追溯证据样本，源记录全程原样留存。

- 后端：FastAPI + SQLAlchemy + PostgreSQL（Swagger UI 自带）
- 前端：Vue 3 + Vite + Element Plus
- 全部业务数据均为**虚构演示数据**，首次启动自动注入

## 快速开始

### 方式一：Docker Compose 一键启动（推荐）

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端工作台 | http://localhost:8080 |
| 后端 API / Swagger UI | http://localhost:8000/docs |
| PostgreSQL | localhost:5432（ccdev/ccdev） |

后端启动时自动建表；空库自动注入种子数据（幂等，重复启动不重复插入）。

### 方式二：本地开发

前置：Python 3.12、Node 22、PostgreSQL（库/用户/密码 `ccdev`）。

```bash
# 后端（终端 1）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# 若清华镜像 403，改用 -i https://mirrors.aliyun.com/pypi/simple/
.venv/bin/uvicorn app.main:app --reload --port 8000

# 前端（终端 2）
cd frontend
npm install        # 已配置 npmmirror 源
npm run dev        # http://localhost:5173 ，/api 自动代理到 8000
```

连接其他数据库：`DATABASE_URL=postgresql+psycopg2://user:pass@host:5432/dbname .venv/bin/uvicorn app.main:app`

### 测试账号

| 账号 | 密码 | 角色 | 说明 |
| --- | --- | --- | --- |
| admin | admin123 | 数据治理管理员 | 目录维护、批次开通、伦理失效/恢复、全部查询 |
| wangjianguo | wang123 | 课题负责人（PI） | PRJ-A 负责人，可开通批次、查询/导出 |
| zhangmin | zhang123 | 数据分析师 | **同时是 PRJ-A 与 PRJ-B 成员**（跨课题边界演示） |
| zhaolei | zhao123 | 数据分析师 | PRJ-A 统计师角色（仅查询、不可导出） |
| auditor | audit123 | 审计员 | 访问依据回查 |

## 核心设计：资格模型取舍

题目给出两种授权模式，本系统**实现「独立资格实例」模式**，理由与适用边界如下：

| 维度 | 独立资格实例（本系统） | 项目级资格包 |
| --- | --- | --- |
| 记录数 | 每个（项目×产品×用途）一条，关系多时记录多 | 每项目一条，记录少 |
| 审计 | 实例自带投影快照与依据，回查直观 | 需重放求交才能还原当时字段 |
| 撤回传播 | 只撤单个实例，影响面明确；但关系多时撤回批量大 | 一次撤回整包，传播范围大、需重算 |
| 查询路径 | 访问时按三元组直接命中投影，O(1) 绑定 | 每次访问需指定用途并现场求交，计算更重 |
| 适用场景 | 关系数量可控、查询频繁、变更（撤回/伦理失效）需精确定位 | 关系极多、查询少、变更以整包为单位 |

**两种模式共有的不变量（本系统强制）**：一次访问只绑定**一个用途**，可用字段 = 该用途求交结果，**绝不对同一成员的多个用途、多个课题取并集扩权**。成员张敏同时在 PRJ-A（TRAIN，L3）与 PRJ-B（EXTRACT，L3）任职：她以 PRJ-B 身份访问时只能命中 PRJ-B 的实例；在 PRJ-A 内用窄用途 PUBLISH（L2）访问时，也不会并入 TRAIN 的 L3 字段。

### 资格编译器求交规则（`backend/app/services/compiler.py`）

- 敏感等级上限 = min（伦理批件上限， 用途条件上限）
- 禁用标签 = 伦理禁用 ∪ 用途禁用（直接标识符 / 准标识符 / 遗传信息）
- 字段有效窗口 = 字段可用期 ∩ 资格有效期；资格有效期 = min（伦理有效期止， 课题结题日）
- 成员范围 = 签发时在职且在任期内的成员（快照进实例）
- 伦理批件失效 / 用途未申报 / 无在职成员 / 投影为空 → 拒绝签发

### 批次处理与伦理失效

开通批次逐项编译，**每项实时重查伦理状态**：处理中失效的项标记「签发失败」并记录原因，已完成项保持「已签发」独立状态；批次状态只能是 完成 / 部分完成 / 失败，**绝不整体假报成功**。

### 额度账本

- 并发占用：账户行级 `SELECT ... FOR UPDATE` 串行化「检查 + 占用」，占用数绝不超过上限（有多线程测试佐证）
- 幂等扣减：用量事件以 `idempotency_key` 全局唯一，断线重试重复上报**只扣一次**，每次上报（含重复）都留痕，重复回执可按键回查
- 访问请求级幂等：`request_id` 唯一，重试返回同一访问事件，不重复扣额度

### 审计回查

每次访问把**当时的产品定义（含目录版本）、资格依据（伦理批件/用途条件/成员范围快照）、额度变化（占用、回执、扣减后余额）**整体快照进访问事件；回查时与当前目录逐字段对比（等级/标签/窗口/增删差异），目录后续变更不影响历史快照。

## 数据产品批次质量认证

### 两条互补的判定路线（按字段风险与基线代表性组合）

| 路线 | 机制 | 优点 | 局限与本系统的应对 |
| --- | --- | --- | --- |
| 硬性数据契约 | 按字段预维护规则，逐项校验缺失率、非法值、唯一性、跨字段一致性 | 结果稳定、解释直接、可复算 | 会把临床可接受例外也阻断、需持续维护规则 → 规则分**阻断型/观察型**，观察型失败只降到 B 不判 C |
| 历史基线漂移 | 以已确认合格的历史批次建立分布基线与漂移区间 | 能发现未知变化 | 受历史偏倚、季节变化、小样本噪声影响 → 建**同季节基线**识别合法季节漂移；样本不足一律标「证据不足」，绝不推断无漂移 |

**组合原则（强制不变量）**：关键字段（高风险）未达 A 时，**不能仅凭批次总体通过率放行**——认证结论由逐字段适用等级汇总，任一关键字段判 C 则整批「不通过」。

### 数据模型与版本化

- 批次清单（`data_batches`）固定四要素：**中心、产品分区、字段字典版本、统计时间窗**；源记录（`batch_records.payload`）**原样落库、只增不改**（无更新/删除端点），证据样本以 `record_key` 回溯原始记录。
- 契约规则（`quality_rules`）带规则版本，并可绑定字段字典版本（`dict_version` 为空表示与版本无关的通用规则）。
- 分布基线（`distribution_baselines`）按（产品 × 分区 × 字段 × 字典版本）隔离，含总体基线与分季节基线。
- 每次认证生成新版本（`quality_certifications` + `field_quality_results`）：**批次更正或规则调整都产生新认证版本，旧认证完整保留**，目录始终引用明确的批次与规则版本。

### 关键判定规则（对应题目硬性要求）

1. **字典版本变化不拼接漂移**：存在其他字典版本的历史基线时，字段漂移结论为「版本不可比」，新旧值域绝不混合计算；版本专属契约规则也不再套用旧代码表。
2. **成对字段按记录级联合比例报告**：两个必须成对出现的字段，输出双全 / 仅甲方 / 仅乙方 / 双缺四象限比例与破坏率；关系破坏会**同时阻断两个字段**，不会各自单独通过而掩盖关系破坏。
3. **小样本证据不足**：基线侧或本批侧样本低于稳定阈值（30）时标「证据不足（I）」，不推断无漂移，也不进入确认性研究字段集。
4. **合法季节漂移**：相对总体基线超阈、但与同季节历史基线一致的波动，判「无漂移（合法季节漂移）」，字段仍可保持 A 级。
5. **适用等级**：`A` 可用于确认性研究 / `B` 仅限探索性研究 / `C` 不可用于研究 / `I` 证据不足；认证结果同时列出各等级字段清单与研究目的适配。

### 内置验收样例（虚构演示数据，随启动自动注入）

| 批次 | 场景 | 认证结论 |
| --- | --- | --- |
| `DQ-HIST-LAB/IMG-*` | 跨四季历史合格批次（含同季节模式），建立分布基线 | 通过（基线建立批次） |
| `DQ-CUR-LAB-OK` | 对照批次，契约全过、漂移可被同季节基线解释 | 通过，全 A |
| `DQ-CUR-LAB-MISSING` | 关键字段缺失、非法枚举、超范围、参考方法-结果范围矛盾 | 不通过（test_result/subject_code/abnormal_flag 判 C） |
| `DQ-CUR-IMG-PAIR` | 检查日期存在而关键序列缺失 | 不通过（联合破坏率 25%，exam_date 与 image_abstract 同判 C） |
| `DQ-CUR-LAB-SEASON` | 季节性偏高，同季节基线可解释 | 通过（合法季节漂移，无漂移） |
| `DQ-CUR-LAB-DICT-V2` | 代码表升级 `DICT-2024.2 → DICT-2026.1` | 证据不足（全字段「版本不可比」，不拼接漂移） |
| `DQ-CUR-LAB-RARE` | 稀有队列分区仅 8 条 | 证据不足（小样本，不推断无漂移） |

## 验证方式

### 自动化验收（已实际执行通过）

```bash
cd backend
.venv/bin/python -m pytest tests/ -q     # 20 passed（独立测试库 ccdev_test，不影响演示数据）
```

覆盖题目要求的全部验收点：

| 验收点 | 用例 |
| --- | --- |
| 字段交集（等级/标签/窗口裁剪） | `test_field_intersection` |
| 资格边界（跨课题不扩权、多用途不并集、越界字段拒绝） | `test_cross_project_and_purpose_boundary`、`test_export_rules` |
| 伦理失效批次（部分完成/失败、不假报成功、失效后拒发） | `test_ethics_invalid_batch_partial` |
| 并发额度占用（API 层 5 线程抢 2 槽、服务层行锁直测） | `test_concurrent_reservation_limit`、`test_service_level_row_lock` |
| 重复事件（只扣一次、重复回执可查、访问重试幂等、额度耗尽 409） | `test_duplicate_usage_report_idempotent`、`test_access_retry_idempotent`、`test_quota_exhaustion` |
| 访问依据回查（产品/资格/额度快照 + 目录变更对比 + 审计权限） | `test_audit_reconstruction` |
| 缺失字段/非法值/参考方法矛盾（逐字段 C 级、证据回溯、总体通过率不放行关键字段） | `test_missing_illegal_and_ref_contradiction` |
| 成对字段记录级联合比例（关系破坏同时阻断双方） | `test_pair_field_joint_ratio` |
| 合法季节漂移（同季节基线解释，字段保持 A） | `test_legitimate_seasonal_drift` |
| 代码表升级（版本不可比、不拼接漂移、旧规则不套用、基线隔离） | `test_code_table_upgrade_not_concatenated` |
| 小样本分区（证据不足、不推断无漂移） | `test_small_sample_insufficient` |
| 规则调整重认证（新版本生成、旧认证保留） | `test_rule_adjust_recertify_versions` |
| 批次更正（新建批次、旧批次/旧认证保留） | `test_batch_correction_keeps_history` |
| 源记录只读不可变 + 写操作权限（ADMIN 独占） | `test_source_records_immutable_and_permissions` |
| API 入库即认证端到端（源记录原样不改写） | `test_api_batch_ingest_and_certify` |

### 手工 UI 验收路径

1. **产品目录**：admin 登录 → 产品目录 → 点开「检验指标数据产品」→ 查看字段语义/敏感等级/可用时间范围 → 编辑 `test_result` 为 L4 → 目录版本 v1→v2，变更日志留痕。
2. **资格开通**：资格开通工作台 → 新建批次：加三项（PRJ-A×P-FU×TRAIN、PRJ-C×P-LAB×REVIEW、PRJ-C×P-IMG×REVIEW）→ 提交 → 批次「部分完成」：PRJ-A 项已签发，PRJ-C 两项「签发失败（伦理失效）」。点实例「详情」看字段投影与资格依据。
3. **资格边界**：zhangmin 登录 → 数据访问模拟 → 选 PRJ-B / P-LAB / TRAIN → 拒绝「无已签发资格」；改选 PRJ-B / P-IMG / EXTRACT → 成功，仅 7 个非 L4 字段；再选 PRJ-A / P-LAB / PUBLISH → 仅 5 个低敏字段（不并入 TRAIN 的 L3 字段）。
4. **并发额度**：额度账本 → 对 PRJ-B（上限 2）连点 3 次「占用一个槽位」→ 第 3 次提示已达上限 → 释放一个后可再占用。
5. **重复事件**：额度账本 → 上报用量（机时 2.5，记下幂等键）→ 点「同一键再报一次」→ 提示重复未扣减 → 回执查询输入该键 → 可见 1 首次 + 1 重复回执，账户只扣 2.5。
6. **访问依据回查**：auditor 登录 → 审计查询 → 点任一成功事件 → 还原当时产品定义、伦理批件依据、额度回执；第 1 步改过字段后，此处「当时 vs 现在」出现 L3→L4 差异。
7. **批次质量认证**：admin 登录 → 批次质量认证 → 批次认证页签：
   - 点 `DQ-CUR-LAB-MISSING` → 结论「不通过」，`test_result`/`subject_code`/`abnormal_flag` 为 C 级，查看缺失率、参考方法矛盾与证据样本；点证据主键可回溯源记录原样 JSON。
   - 点 `DQ-CUR-IMG-PAIR` → `exam_date` 与 `image_abstract` 同判 C，联合比例显示双全 75%/仅检查日期 25%。
   - 点 `DQ-CUR-LAB-SEASON` → 全 A，漂移说明为「合法季节漂移」；`DQ-CUR-LAB-DICT-V2` → 全字段「版本不可比」；`DQ-CUR-LAB-RARE` → 全 I「证据不足」。
   - 切换认证版本单选按钮可查看历史版本；「按当前规则重新认证」生成新版本且旧版本保留。
   - 「硬性数据契约」页签可调整规则（升版本）；「分布基线」页签可查看各字段基线与同季节基线、依据批次。

## API 概览

Swagger UI：`/docs`（OpenAPI 3.1）。主要端点：

- `POST /api/auth/login` 登录；`GET /api/auth/me`
- `GET /api/catalog/products`、`GET /api/catalog/products/{id}`、`PUT /api/catalog/products/{id}/fields/{fid}`（目录变更留痕）、`GET /api/catalog/products/{id}/changes`
- `GET /api/projects`、`GET /api/projects/{id}`、`POST /api/projects/{id}/ethics/{eid}/revoke|restore`
- `POST /api/qualifications/batches`（批次开通）、`GET /api/qualifications[/…]`、`POST /api/qualifications/{id}/revoke`
- `POST /api/access/query`（数据访问，request_id 幂等）、`GET /api/access/events`
- `GET /api/quota/accounts`、`POST /api/quota/reservations[/{id}/release]`、`POST /api/quota/usage`（幂等键）、`GET /api/quota/usage/by-key/{key}/receipts`
- `GET /api/audit/access/{id}`（访问依据回查，ADMIN/AUDITOR）
- `POST /api/quality/batches`（批次入库即认证，ADMIN）、`GET /api/quality/batches[/{id}]`、`GET /api/quality/batches/{id}/records[/by-key/{key}]`（源记录只读回溯）
- `POST /api/quality/batches/{id}/correction`（批次更正，新建批次留痕）、`POST /api/quality/batches/{id}/recertify`（规则调整后重认证，生成新版本）
- `GET /api/quality/certifications[/{id}]`（认证版本与逐字段结果/证据）、`GET|POST /api/quality/rules`、`POST /api/quality/rules/{id}/adjust`（规则升版本）
- `GET /api/quality/baselines`、`POST /api/quality/baselines/rebuild`（分布基线按字典版本隔离）

## 目录结构

```
backend/
  app/
    main.py            # 应用入口（lifespan 建表 + 空库自动播种）
    models.py          # 目录/课题/伦理/资格实例/批次/额度/访问事件 + 质量认证六表
    services/compiler.py  # 资格编译器（求交）
    services/quota.py     # 并发占用（行锁）+ 幂等扣减
    services/quality.py   # 质量认证引擎（契约校验 + 分布漂移 + 季节基线 + 适用等级）
    routers/           # auth/catalog/projects/qualifications/access/quota/audit/quality
    seed.py            # 虚构演示数据（目录/伦理/成员/额度/首批资格/示范访问）
    seed_quality.py    # 质量契约规则、历史基线批次、五类验收场景批次
  tests/test_acceptance.py          # 11 个原有验收用例
  tests/test_quality_acceptance.py  # 9 个批次质量认证验收用例
frontend/
  src/views/           # 目录/课题/开通工作台/质量认证/访问模拟/额度/审计/登录
docker-compose.yml     # db + backend + frontend 一键启动
```

## 说明与限制

- 本容器内无 Docker 守护进程，Compose 配置未在本机实际构建；后端（uvicorn 启动 + pytest 20 用例全通过 + HTTP 端到端冒烟）与前端（vite build 通过，含质量认证页）已在容器内以预装运行时实际验证。
- 质量认证的分布漂移采用 TV 距离/双比例 z 检验（分类字段）与均值 z/PSI（数值字段），阈值集中定义在 `services/quality.py`；演示数据为确定性虚构数据，真实环境需按字段临床特性标定阈值与稳定样本量。
- 认证为演示级 HMAC 令牌，口令 PBKDF2 散列；生产使用需替换 `SECRET_KEY` 并接入正式身份体系。
- 数据库 `ccdev` 账号仅供本隔离环境开发测试，非生产配置。
