<template>
  <div>
    <el-tabs v-model="tab">
      <!-- ===================== 批次认证 ===================== -->
      <el-tab-pane label="批次认证" name="batch">
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <b>数据产品批次清单（中心 / 分区 / 字典版本 / 统计时间窗固定）</b>
              <div style="display: flex; gap: 8px">
                <el-select v-model="filterProduct" size="small" clearable placeholder="产品"
                  style="width: 150px" @change="loadBatches">
                  <el-option v-for="p in products" :key="p.id" :value="p.id" :label="p.code" />
                </el-select>
                <el-input v-model="filterPartition" size="small" clearable placeholder="分区"
                  style="width: 140px" @change="loadBatches" />
                <el-button size="small" @click="loadBatches">刷新</el-button>
              </div>
            </div>
          </template>
          <el-table :data="batches" size="small" v-loading="loading" @row-click="openBatch"
            row-class-name="clickable">
            <el-table-column prop="batch_no" label="批次号" width="175" />
            <el-table-column prop="product_code" label="产品" width="90" />
            <el-table-column prop="center_code" label="中心" width="120" />
            <el-table-column prop="partition_name" label="产品分区" min-width="120" />
            <el-table-column prop="dict_version" label="字典版本" width="130" />
            <el-table-column label="统计时间窗" width="180">
              <template #default="{ row }">{{ row.window_from }} ~ {{ row.window_to }}</template>
            </el-table-column>
            <el-table-column prop="record_count" label="记录数" width="75" />
            <el-table-column label="最新认证" width="100">
              <template #default="{ row }">
                <el-tag :type="decisionType(row.latest_decision)" size="small">
                  {{ row.latest_decision || '待认证' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="版本" width="65">
              <template #default="{ row }">v{{ row.latest_version || '—' }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ===================== 契约规则 ===================== -->
      <el-tab-pane label="硬性数据契约" name="rules">
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <b>质量规则（缺失 / 非法值 / 唯一性 / 跨字段一致性，调整即升规则版本）</b>
              <el-select v-model="ruleProduct" size="small" style="width: 160px" @change="loadRules">
                <el-option v-for="p in products" :key="p.id" :value="p.id" :label="p.code" />
              </el-select>
            </div>
          </template>
          <el-table :data="rules" size="small">
            <el-table-column prop="field_name" label="字段" width="130" />
            <el-table-column prop="rule_type" label="规则类型" width="100">
              <template #default="{ row }">{{ ruleTypeLabel[row.rule_type] || row.rule_type }}</template>
            </el-table-column>
            <el-table-column label="字典版本" width="120">
              <template #default="{ row }">
                <el-tag size="small" :type="row.dict_version ? 'warning' : 'info'">
                  {{ row.dict_version || '通用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="参数" min-width="220">
              <template #default="{ row }">
                <code class="param">{{ JSON.stringify(row.params) }}</code>
              </template>
            </el-table-column>
            <el-table-column label="阻断" width="70">
              <template #default="{ row }">
                <el-tag :type="row.blocking ? 'danger' : 'info'" size="small">
                  {{ row.blocking ? '阻断' : '观察' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="风险" width="65">
              <template #default="{ row }">
                <el-tag :type="riskType(row.risk_level)" size="small">{{ row.risk_level }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="rule_version" label="版本" width="65" />
            <el-table-column label="操作" width="90" v-if="isAdmin">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="openRule(row)">调整</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>

      <!-- ===================== 分布基线 ===================== -->
      <el-tab-pane label="分布基线" name="baselines">
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <b>历史合格批次分布基线（按字段字典版本隔离，含同季节基线）</b>
              <el-button v-if="isAdmin" size="small" type="primary" @click="rebuildDlg = true">
                重建基线
              </el-button>
            </div>
          </template>
          <el-table :data="baselines" size="small">
            <el-table-column prop="partition_name" label="分区" min-width="120" />
            <el-table-column prop="field_name" label="字段" width="140" />
            <el-table-column prop="dict_version" label="字典版本" width="130" />
            <el-table-column prop="sample_size" label="样本量" width="80" />
            <el-table-column label="分布类型" width="95">
              <template #default="{ row }">
                {{ { numeric: '数值', categorical: '分类', identifier: '标识', date: '日期' }[row.stats_kind] || row.stats_kind }}
              </template>
            </el-table-column>
            <el-table-column label="关键统计" min-width="200">
              <template #default="{ row }">
                <span v-if="row.stats_kind === 'numeric'">
                  均值 {{ row.stats.mean?.toFixed(3) }} ｜ 标准差 {{ row.stats.std?.toFixed(3) }}
                </span>
                <span v-else-if="row.stats_kind === 'categorical'">
                  {{ Object.keys(row.stats.freq || {}).length }} 个类目
                </span>
                <span v-else>以契约规则约束，不做漂移</span>
              </template>
            </el-table-column>
            <el-table-column label="季节基线" width="120">
              <template #default="{ row }">
                {{ Object.keys(row.seasonal_stats || {}).join('、') || '—' }}
              </template>
            </el-table-column>
            <el-table-column label="依据批次" min-width="120">
              <template #default="{ row }">#{{ row.source_batch_ids.join('、#') }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- ===================== 批次认证详情抽屉 ===================== -->
    <el-drawer v-model="batchDrawer" :title="`批次认证 ${currentBatch?.batch_no || ''}`" size="72%">
      <template v-if="currentBatch">
        <el-descriptions :column="3" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="产品">{{ currentBatch.product_code }}</el-descriptions-item>
          <el-descriptions-item label="中心 / 分区">{{ currentBatch.center_code }} / {{ currentBatch.partition_name }}</el-descriptions-item>
          <el-descriptions-item label="字典版本">{{ currentBatch.dict_version }}</el-descriptions-item>
          <el-descriptions-item label="统计时间窗" :span="2">
            {{ currentBatch.window_from }} ~ {{ currentBatch.window_to }}
          </el-descriptions-item>
          <el-descriptions-item label="源记录数">{{ currentBatch.record_count }}（原样留存，只读）</el-descriptions-item>
        </el-descriptions>

        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px">
          <div>
            <span style="margin-right: 10px">认证版本：</span>
            <el-radio-group v-model="currentCertId" size="small" @change="loadCert">
              <el-radio-button v-for="v in currentBatch.cert_versions" :key="v.id" :value="v.id">
                v{{ v.version }} {{ v.decision }}
              </el-radio-button>
            </el-radio-group>
          </div>
          <el-button v-if="isAdmin" size="small" type="warning" @click="recertify">
            按当前规则重新认证（生成新版本）
          </el-button>
        </div>

        <template v-if="cert">
          <el-alert :type="decisionType(cert.decision)" :closable="false" style="margin-bottom: 10px">
            <template #title>
              认证结论【{{ cert.decision }}】｜规则版本 v{{ cert.rule_version }}｜
              字段通过 {{ cert.passed_fields }}/{{ cert.field_count }}｜
              阻断 {{ cert.blocked_fields }}｜证据不足 {{ cert.insufficient_fields }}｜
              触发：{{ cert.trigger }}
            </template>
            <div style="margin-top: 4px; font-size: 12px">{{ cert.summary }}</div>
          </el-alert>

          <el-descriptions :column="2" border size="small" style="margin-bottom: 12px">
            <el-descriptions-item label="可用于确认性研究（A）">
              {{ cert.research_fitness.confirmatory.join('、') || '无' }}
            </el-descriptions-item>
            <el-descriptions-item label="仅限探索性研究（B）">
              {{ (cert.research_fitness.exploratory || []).filter((f) => !cert.research_fitness.confirmatory.includes(f)).join('、') || '无' }}
            </el-descriptions-item>
            <el-descriptions-item label="不可用于研究（C）">
              <span class="danger-text">{{ cert.research_fitness.unusable.join('、') || '无' }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="证据不足（I）">
              <span class="warn-text">{{ cert.research_fitness.insufficient.join('、') || '无' }}</span>
            </el-descriptions-item>
          </el-descriptions>

          <el-table :data="cert.field_results" size="small" border max-height="420">
            <el-table-column prop="field_name" label="字段" width="130" fixed />
            <el-table-column label="适用等级" width="80">
              <template #default="{ row }">
                <el-tag :type="gradeType(row.fitness_grade)" size="small">{{ row.fitness_grade }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="漂移结论" width="100">
              <template #default="{ row }">
                <el-tag :type="driftType(row.drift_status)" size="small">{{ row.drift_status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="缺失率" width="80">
              <template #default="{ row }">{{ (row.metrics.missing_rate * 100).toFixed(1) }}%</template>
            </el-table-column>
            <el-table-column label="非法/重复" width="90">
              <template #default="{ row }">
                {{ row.metrics.invalid || 0 }} / {{ row.metrics.duplicate || 0 }}
              </template>
            </el-table-column>
            <el-table-column label="阻断原因 / 漂移说明" min-width="240">
              <template #default="{ row }">
                <div v-for="(b, i) in row.block_reasons" :key="i" class="danger-text">• {{ b.message }}</div>
                <div v-if="!row.block_reasons.length && row.drift_detail.message" class="muted">
                  {{ row.drift_detail.message }}
                </div>
              </template>
            </el-table-column>
            <el-table-column label="证据" width="80" fixed="right">
              <template #default="{ row }">
                <el-button size="small" text type="primary" :disabled="!row.evidence_samples.length"
                  @click="openEvidence(row)">
                  {{ row.evidence_samples.length || '—' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </template>
    </el-drawer>

    <!-- ===================== 证据样本对话框（回溯源记录） ===================== -->
    <el-dialog v-model="evidenceDlg" :title="`证据样本 · ${evidenceField?.field_name || ''}`" width="720px">
      <el-table :data="evidenceField?.evidence_samples || []" size="small" max-height="360">
        <el-table-column prop="record_key" label="源记录主键" width="200">
          <template #default="{ row }">
            <el-link type="primary" @click="lookupRecord(row.record_key)">{{ row.record_key }}</el-link>
          </template>
        </el-table-column>
        <el-table-column prop="issue" label="问题" width="200" />
        <el-table-column label="问题字段值" min-width="220">
          <template #default="{ row }"><code>{{ JSON.stringify(row.values) }}</code></template>
        </el-table-column>
      </el-table>
      <el-alert v-if="sourceRecord" type="info" :closable="false" style="margin-top: 12px">
        <template #title>
          源记录 {{ sourceRecord.record_key }} 原样数据（BatchRecord.payload，认证不改写）：
          <code>{{ JSON.stringify(sourceRecord.payload) }}</code>
        </template>
      </el-alert>
    </el-dialog>

    <!-- ===================== 规则调整对话框 ===================== -->
    <el-dialog v-model="ruleDlg" :title="`调整契约规则：${editingRule?.field_name || ''}`" width="560px">
      <el-form v-if="editingRule" label-width="100px">
        <el-form-item label="规则类型">{{ ruleTypeLabel[editingRule.rule_type] }}</el-form-item>
        <el-form-item label="参数 JSON">
          <el-input v-model="ruleParamsText" type="textarea" :rows="5" />
        </el-form-item>
        <el-form-item label="是否阻断">
          <el-switch v-model="editingRule.blocking" active-text="阻断型" inactive-text="观察型" />
        </el-form-item>
        <el-form-item label="字段风险">
          <el-select v-model="editingRule.risk_level">
            <el-option v-for="r in ['高', '中', '低']" :key="r" :value="r" :label="r" />
          </el-select>
        </el-form-item>
        <el-alert type="warning" :closable="false"
          title="保存后规则版本 +1；已产生的认证仍引用旧版本，需对批次执行重认证才生效，旧认证保留。" />
      </el-form>
      <template #footer>
        <el-button @click="ruleDlg = false">取消</el-button>
        <el-button type="primary" @click="saveRule">保存并升版本</el-button>
      </template>
    </el-dialog>

    <!-- ===================== 重建基线对话框 ===================== -->
    <el-dialog v-model="rebuildDlg" title="重建分布基线" width="480px">
      <el-form label-width="100px">
        <el-form-item label="产品">
          <el-select v-model="rebuildForm.product_id" style="width: 100%">
            <el-option v-for="p in products" :key="p.id" :value="p.id" :label="p.code" />
          </el-select>
        </el-form-item>
        <el-form-item label="分区"><el-input v-model="rebuildForm.partition_name" /></el-form-item>
        <el-form-item label="字段名"><el-input v-model="rebuildForm.field_name" /></el-form-item>
        <el-form-item label="字典版本"><el-input v-model="rebuildForm.dict_version" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="rebuildDlg = false">取消</el-button>
        <el-button type="primary" @click="doRebuild">重建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { currentUser } from '../api'

const tab = ref('batch')
const isAdmin = ref(currentUser()?.role === 'ADMIN')
const products = ref([])
const batches = ref([])
const rules = ref([])
const baselines = ref([])
const loading = ref(false)
const filterProduct = ref(null)
const filterPartition = ref('')
const ruleProduct = ref(null)

const batchDrawer = ref(false)
const currentBatch = ref(null)
const currentCertId = ref(null)
const cert = ref(null)
const evidenceDlg = ref(false)
const evidenceField = ref(null)
const sourceRecord = ref(null)
const ruleDlg = ref(false)
const editingRule = ref(null)
const ruleParamsText = ref('')
const rebuildDlg = ref(false)
const rebuildForm = ref({ product_id: null, partition_name: '', field_name: '', dict_version: '' })

const ruleTypeLabel = {
  missing: '缺失', invalid: '非法值', uniqueness: '唯一性', consistency: '跨字段一致性',
}
const decisionType = (d) => ({ 通过: 'success', 有条件通过: 'warning', 不通过: 'danger', 证据不足: 'info' }[d] || 'info')
const gradeType = (g) => ({ A: 'success', B: 'warning', C: 'danger', I: 'info' }[g] || 'info')
const driftType = (s) => ({ 无漂移: 'success', 漂移: 'danger', 证据不足: 'warning', 版本不可比: 'info', 未评估: 'info' }[s] || 'info')
const riskType = (r) => ({ 高: 'danger', 中: 'warning', 低: 'info' }[r] || 'info')

async function loadBatches() {
  loading.value = true
  try {
    const params = {}
    if (filterProduct.value) params.product_id = filterProduct.value
    if (filterPartition.value) params.partition_name = filterPartition.value
    batches.value = (await api.get('/quality/batches', { params })).data
  } finally {
    loading.value = false
  }
}

async function loadRules() {
  const params = {}
  if (ruleProduct.value) params.product_id = ruleProduct.value
  rules.value = (await api.get('/quality/rules', { params })).data
}

async function loadBaselines() {
  baselines.value = (await api.get('/quality/baselines')).data
}

async function openBatch(row) {
  currentBatch.value = await (await api.get(`/quality/batches/${row.id}`)).data
  currentCertId.value = currentBatch.value.cert_versions[0]?.id || null
  batchDrawer.value = true
  await loadCert()
}

async function loadCert() {
  if (!currentCertId.value) {
    cert.value = null
    return
  }
  cert.value = (await api.get(`/quality/certifications/${currentCertId.value}`)).data
}

async function recertify() {
  const { value } = await ElMessageBox.prompt('确认按当前规则对该批次重新认证？将生成新认证版本，旧版本保留。',
    '重认证', { inputValue: '规则调整后重认证' })
  const data = (await api.post(`/quality/batches/${currentBatch.value.id}/recertify`, {
    trigger: '规则调整', note: value || '' })).data
  ElMessage.success(`已生成认证版本 v${data.version}：${data.decision}`)
  await openBatch(currentBatch.value)
  await loadBatches()
}

function openEvidence(row) {
  evidenceField.value = row
  sourceRecord.value = null
  evidenceDlg.value = true
}

async function lookupRecord(key) {
  sourceRecord.value = (await api.get(
    `/quality/batches/${currentBatch.value.id}/records/by-key/${encodeURIComponent(key)}`)).data
}

function openRule(row) {
  editingRule.value = { ...row }
  ruleParamsText.value = JSON.stringify(row.params, null, 2)
  ruleDlg.value = true
}

async function saveRule() {
  let params
  try {
    params = JSON.parse(ruleParamsText.value)
  } catch {
    ElMessage.error('参数 JSON 格式非法')
    return
  }
  await api.post(`/quality/rules/${editingRule.value.id}/adjust`, {
    params, blocking: editingRule.value.blocking, risk_level: editingRule.value.risk_level })
  ElMessage.success('规则已升版本；请对相关批次执行重认证')
  ruleDlg.value = false
  await loadRules()
}

async function doRebuild() {
  const f = rebuildForm.value
  await api.post('/quality/baselines/rebuild', null, { params: {
    product_id: f.product_id, partition_name: f.partition_name,
    field_name: f.field_name, dict_version: f.dict_version } })
  ElMessage.success('基线已按同字典版本合格历史批次重建')
  rebuildDlg.value = false
  await loadBaselines()
}

onMounted(async () => {
  products.value = (await api.get('/catalog/products')).data
  ruleProduct.value = products.value[0]?.id || null
  rebuildForm.value.product_id = ruleProduct.value
  await Promise.all([loadBatches(), loadRules(), loadBaselines()])
})
</script>

<style scoped>
.param { font-size: 11px; color: #555; word-break: break-all; }
.muted { color: #909399; font-size: 12px; }
.danger-text { color: #c45656; font-size: 12px; }
.warn-text { color: #b88230; font-size: 12px; }
h4 { margin: 10px 0; }
</style>
<style>
.clickable { cursor: pointer; }
</style>
