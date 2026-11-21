<template>
  <div>
    <el-row :gutter="14">
      <el-col :span="9">
        <el-card shadow="never" v-if="canIssue">
          <template #header><b>新建开通批次</b></template>
          <el-input v-model="batchTitle" placeholder="批次名称" size="small" style="margin-bottom: 10px" />
          <div v-for="(item, i) in items" :key="i" class="item-row">
            <el-select v-model="item.project_id" placeholder="课题" size="small" @change="item.purpose_code = ''">
              <el-option v-for="p in projects" :key="p.id" :value="p.id" :label="p.code" />
            </el-select>
            <el-select v-model="item.product_id" placeholder="产品" size="small">
              <el-option v-for="p in products" :key="p.id" :value="p.id" :label="p.code" />
            </el-select>
            <el-select v-model="item.purpose_code" placeholder="用途" size="small">
              <el-option v-for="u in purposesOf(item.project_id)" :key="u.purpose_code"
                :value="u.purpose_code" :label="u.purpose_code" />
            </el-select>
            <el-button size="small" text type="danger" @click="items.splice(i, 1)">删</el-button>
          </div>
          <el-button size="small" @click="items.push({ project_id: null, product_id: null, purpose_code: '' })">
            + 添加一项
          </el-button>
          <el-button type="primary" size="small" style="margin-left: 8px" :loading="submitting"
            @click="submitBatch">提交批次</el-button>
          <el-alert type="info" :closable="false" style="margin-top: 10px"
            title="逐项编译：伦理失效的项不得签发；批次状态 = 完成 / 部分完成 / 失败。" />
        </el-card>

        <el-card shadow="never" style="margin-top: 14px">
          <template #header><b>批次记录</b></template>
          <el-table :data="batches" size="small" @row-click="openBatch" row-class-name="clickable">
            <el-table-column prop="batch_no" label="批次号" width="130" />
            <el-table-column prop="status" label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="batchType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="成/败" width="70">
              <template #default="{ row }">{{ row.succeeded }}/{{ row.failed }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="15">
        <el-card shadow="never">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <b>资格实例（项目 × 产品 × 用途 隔离）</b>
              <el-select v-model="filterStatus" size="small" style="width: 120px" clearable placeholder="状态"
                @change="loadQuals">
                <el-option v-for="s in ['已签发', '签发失败', '已撤回']" :key="s" :value="s" :label="s" />
              </el-select>
            </div>
          </template>
          <el-table :data="quals" size="small" v-loading="qualLoading">
            <el-table-column prop="project_code" label="课题" width="80" />
            <el-table-column prop="product_code" label="产品" width="85" />
            <el-table-column prop="purpose_code" label="用途" width="90" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="qualType(row.status)" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="有效期" width="195">
              <template #default="{ row }">
                <span v-if="row.status !== '签发失败'">{{ row.valid_from }} ~ {{ row.valid_to }}</span>
                <span v-else>—</span>
              </template>
            </el-table-column>
            <el-table-column prop="field_count" label="字段数" width="70" />
            <el-table-column label="操作" width="140">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="openQual(row)">详情</el-button>
                <el-button v-if="canIssue && row.status === '已签发'" size="small" text type="danger"
                  @click="revokeQual(row)">撤回</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>

    <el-drawer v-model="batchDrawer" :title="`批次 ${currentBatch?.batch_no || ''}`" size="55%">
      <template v-if="currentBatch">
        <el-descriptions :column="4" border size="small" style="margin-bottom: 12px">
          <el-descriptions-item label="状态">
            <el-tag :type="batchType(currentBatch.status)" size="small">{{ currentBatch.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="总数">{{ currentBatch.total }}</el-descriptions-item>
          <el-descriptions-item label="成功">{{ currentBatch.succeeded }}</el-descriptions-item>
          <el-descriptions-item label="失败">{{ currentBatch.failed }}</el-descriptions-item>
        </el-descriptions>
        <el-table :data="currentBatch.items" size="small" border>
          <el-table-column prop="project_name" label="课题" min-width="140" />
          <el-table-column prop="product_name" label="产品" min-width="130" />
          <el-table-column prop="purpose_code" label="用途" width="90" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="qualType(row.status)" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="fail_reason" label="失败原因" min-width="200">
            <template #default="{ row }">{{ row.fail_reason || '—' }}</template>
          </el-table-column>
        </el-table>
      </template>
    </el-drawer>

    <el-drawer v-model="qualDrawer" title="资格实例详情" size="58%">
      <template v-if="currentQual">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="课题">{{ currentQual.project_code }} {{ currentQual.project_name }}</el-descriptions-item>
          <el-descriptions-item label="产品">{{ currentQual.product_code }} {{ currentQual.product_name }}</el-descriptions-item>
          <el-descriptions-item label="用途">{{ currentQual.purpose_code }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="qualType(currentQual.status)" size="small">{{ currentQual.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="有效期">{{ currentQual.valid_from }} ~ {{ currentQual.valid_to }}</el-descriptions-item>
          <el-descriptions-item label="签发目录版本">v{{ currentQual.catalog_version }}</el-descriptions-item>
        </el-descriptions>

        <template v-if="currentQual.status === '已签发'">
          <h4>字段投影（{{ currentQual.field_projection.length }} 个可用字段）</h4>
          <el-table :data="currentQual.field_projection" size="small" border max-height="300">
            <el-table-column prop="field_name" label="字段名" width="120" />
            <el-table-column prop="semantic" label="语义" min-width="150" />
            <el-table-column label="等级" width="60">
              <template #default="{ row }">L{{ row.sensitivity_level }}</template>
            </el-table-column>
            <el-table-column label="有效窗口" width="200">
              <template #default="{ row }">{{ row.window_from }} ~ {{ row.window_to }}</template>
            </el-table-column>
          </el-table>

          <h4>资格依据</h4>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="求交规则">{{ currentQual.basis.rule }}</el-descriptions-item>
            <el-descriptions-item label="求交后敏感上限">L{{ currentQual.basis.effective_max_sensitivity }}</el-descriptions-item>
            <el-descriptions-item label="求交后禁用标签">
              {{ currentQual.basis.effective_forbidden_tags.join('、') || '无' }}
            </el-descriptions-item>
            <el-descriptions-item label="伦理批件">
              <div v-for="e in currentQual.basis.ethics" :key="e.approval_no">
                {{ e.approval_no }}｜{{ e.scope_subjects }}｜上限 L{{ e.max_sensitivity_level }}｜{{ e.valid_from }}~{{ e.valid_to }}
              </div>
            </el-descriptions-item>
            <el-descriptions-item label="覆盖成员">
              {{ currentQual.basis.covered_members.map((m) => `${m.name}(${m.role})`).join('、') }}
            </el-descriptions-item>
            <el-descriptions-item label="被剔除字段">
              <div v-for="e in currentQual.basis.excluded_fields" :key="e.field_name">
                {{ e.field_name }}：{{ e.reason }}
              </div>
            </el-descriptions-item>
          </el-descriptions>
        </template>
        <el-alert v-else type="error" :closable="false" style="margin-top: 12px"
          :title="currentQual.fail_reason || currentQual.revoke_reason || ''" />
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { currentUser } from '../api'

const projects = ref([])
const products = ref([])
const projectDetails = ref({})
const batches = ref([])
const quals = ref([])
const items = ref([{ project_id: null, product_id: null, purpose_code: '' }])
const batchTitle = ref('')
const submitting = ref(false)
const batchDrawer = ref(false)
const currentBatch = ref(null)
const qualDrawer = ref(false)
const currentQual = ref(null)
const filterStatus = ref('')
const qualLoading = ref(false)

const canIssue = computed(() => ['ADMIN', 'PI'].includes(currentUser()?.role))

function batchType(s) {
  return { 完成: 'success', 部分完成: 'warning', 失败: 'danger' }[s] || 'info'
}
function qualType(s) {
  return { 已签发: 'success', 签发失败: 'danger', 已撤回: 'info' }[s] || 'info'
}

function purposesOf(projectId) {
  return projectDetails.value[projectId]?.purposes || []
}

async function ensureProjectDetail(id) {
  if (id && !projectDetails.value[id]) {
    projectDetails.value[id] = (await api.get(`/projects/${id}`)).data
  }
}

async function loadQuals() {
  qualLoading.value = true
  try {
    const qs = filterStatus.value ? `?status=${encodeURIComponent(filterStatus.value)}` : ''
    quals.value = (await api.get(`/qualifications${qs}`)).data
  } finally {
    qualLoading.value = false
  }
}

async function load() {
  const [pj, pd, bt] = await Promise.all([
    api.get('/projects'), api.get('/catalog/products'), api.get('/qualifications/batches'),
  ])
  projects.value = pj.data
  products.value = pd.data
  batches.value = bt.data
  for (const p of pj.data) await ensureProjectDetail(p.id)
  await loadQuals()
}

async function submitBatch() {
  const valid = items.value.filter((i) => i.project_id && i.product_id && i.purpose_code)
  if (!valid.length) {
    ElMessage.warning('请至少完整填写一项')
    return
  }
  submitting.value = true
  try {
    const { data } = await api.post('/qualifications/batches', {
      title: batchTitle.value || '资格开通批次', items: valid,
    })
    if (data.status === '完成') ElMessage.success(`批次完成：${data.succeeded} 项全部签发`)
    else if (data.status === '部分完成') ElMessage.warning(`批次部分完成：成功 ${data.succeeded}，失败 ${data.failed}`)
    else ElMessage.error(`批次失败：${data.failed} 项均未签发`)
    currentBatch.value = data
    batchDrawer.value = true
    items.value = [{ project_id: null, product_id: null, purpose_code: '' }]
    batchTitle.value = ''
    await load()
  } finally {
    submitting.value = false
  }
}

async function openBatch(row) {
  currentBatch.value = (await api.get(`/qualifications/batches/${row.id}`)).data
  batchDrawer.value = true
}

async function openQual(row) {
  currentQual.value = (await api.get(`/qualifications/${row.id}`)).data
  qualDrawer.value = true
}

async function revokeQual(row) {
  const { value } = await ElMessageBox.prompt(
    `撤回（${row.project_code} × ${row.product_code} × ${row.purpose_code}）资格？`, '撤回资格',
    { inputValue: '伦理委员会要求暂停使用' })
  await api.post(`/qualifications/${row.id}/revoke`, { reason: value || '' })
  ElMessage.success('已撤回，仅影响该实例')
  await loadQuals()
}

onMounted(load)
</script>

<style scoped>
.item-row { display: flex; gap: 6px; margin-bottom: 8px; }
.item-row .el-select { flex: 1; }
h4 { margin: 14px 0 8px; }
</style>
