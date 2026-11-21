<template>
  <div>
    <el-row :gutter="14">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header><b>额度账户（已批准预算 / 实际消耗 / 并发占用）</b></template>
          <el-table :data="accounts" size="small" v-loading="loading">
            <el-table-column prop="project_code" label="课题" width="80" />
            <el-table-column label="并发占用" width="130">
              <template #default="{ row }">
                <el-tag :type="row.active_reservations >= row.max_concurrent ? 'danger' : 'success'" size="small">
                  {{ row.active_reservations }} / {{ row.max_concurrent }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="查询次数" min-width="150">
              <template #default="{ row }">
                <el-progress :percentage="pct(row.used_query, row.budget_query)" :stroke-width="14"
                  :format="() => `${row.used_query}/${row.budget_query}`" />
              </template>
            </el-table-column>
            <el-table-column label="导出行数" min-width="150">
              <template #default="{ row }">
                <el-progress :percentage="pct(row.used_export_rows, row.budget_export_rows)" :stroke-width="14"
                  :format="() => `${row.used_export_rows}/${row.budget_export_rows}`" />
              </template>
            </el-table-column>
            <el-table-column label="机时(小时)" min-width="150">
              <template #default="{ row }">
                <el-progress :percentage="pct(row.used_compute_hours, row.budget_compute_hours)" :stroke-width="14"
                  :format="() => `${row.used_compute_hours}/${row.budget_compute_hours}`" />
              </template>
            </el-table-column>
          </el-table>
          <el-button size="small" style="margin-top: 10px" @click="load">刷新</el-button>
        </el-card>

        <el-card shadow="never" style="margin-top: 14px">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <b>并发占用记录</b>
              <div>
                <el-select v-model="acqProject" size="small" style="width: 110px">
                  <el-option v-for="a in accounts" :key="a.project_id" :value="a.project_id" :label="a.project_code" />
                </el-select>
                <el-button size="small" type="primary" @click="acquire">占用一个槽位</el-button>
              </div>
            </div>
          </template>
          <el-table :data="reservations" size="small" max-height="260">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="kind" label="类型" width="60" />
            <el-table-column label="状态" width="80">
              <template #default="{ row }">
                <el-tag :type="row.status === '占用中' ? 'warning' : 'info'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="note" label="备注" min-width="170" />
            <el-table-column prop="created_at" label="占用时间" width="165" />
            <el-table-column label="操作" width="80">
              <template #default="{ row }">
                <el-button v-if="row.status === '占用中'" size="small" text type="primary"
                  @click="release(row)">释放</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="10">
        <el-card shadow="never">
          <template #header><b>上报用量（幂等）</b></template>
          <el-form label-width="90px" size="small">
            <el-form-item label="课题">
              <el-select v-model="usageForm.project_id">
                <el-option v-for="a in accounts" :key="a.project_id" :value="a.project_id" :label="a.project_code" />
              </el-select>
            </el-form-item>
            <el-form-item label="类型">
              <el-radio-group v-model="usageForm.kind">
                <el-radio value="查询">查询</el-radio>
                <el-radio value="导出">导出</el-radio>
                <el-radio value="机时">机时</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="数量">
              <el-input-number v-model="usageForm.amount" :min="0.5" :max="10000" />
            </el-form-item>
            <el-form-item label="幂等键">
              <el-input v-model="usageForm.idempotency_key">
                <template #append><el-button @click="regenKey">换</el-button></template>
              </el-input>
            </el-form-item>
            <el-button type="primary" @click="report(false)">上报</el-button>
            <el-button :disabled="!lastKey" @click="report(true)">同一键再报一次（模拟断线重试）</el-button>
          </el-form>
          <el-alert v-if="reportResult" :type="reportResult.duplicate ? 'warning' : 'success'" :closable="false"
            style="margin-top: 10px"
            :title="`${reportResult.message}｜回执号 ${reportResult.event.receipt_no}`" />
        </el-card>

        <el-card shadow="never" style="margin-top: 14px">
          <template #header><b>回执查询（含重复回执）</b></template>
          <el-input v-model="lookupKey" size="small" placeholder="输入幂等键">
            <template #append><el-button @click="lookup">查询</el-button></template>
          </el-input>
          <template v-if="receipts">
            <el-descriptions :column="1" border size="small" style="margin-top: 10px">
              <el-descriptions-item label="回执号">{{ receipts.event.receipt_no }}</el-descriptions-item>
              <el-descriptions-item label="扣减">
                {{ receipts.event.kind }} × {{ receipts.event.amount }}（只扣一次：{{ receipts.deducted_once ? '是' : '否' }}）
              </el-descriptions-item>
            </el-descriptions>
            <el-table :data="receipts.reports" size="small" style="margin-top: 8px">
              <el-table-column prop="reported_at" label="上报时间" width="165" />
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.is_duplicate ? 'warning' : 'success'" size="small">
                    {{ row.is_duplicate ? '重复回执' : '首次' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="note" label="备注" min-width="150" />
            </el-table>
          </template>
        </el-card>

        <el-card shadow="never" style="margin-top: 14px">
          <template #header><b>用量事件</b></template>
          <el-table :data="usageEvents" size="small" max-height="240">
            <el-table-column prop="created_at" label="时间" width="165" />
            <el-table-column prop="kind" label="类型" width="60" />
            <el-table-column prop="amount" label="数量" width="70" />
            <el-table-column prop="idempotency_key" label="幂等键" min-width="150" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '../api'

const accounts = ref([])
const reservations = ref([])
const usageEvents = ref([])
const loading = ref(false)
const acqProject = ref(null)
const usageForm = reactive({ project_id: null, kind: '机时', amount: 1, idempotency_key: '' })
const reportResult = ref(null)
const lastKey = ref('')
const lookupKey = ref('')
const receipts = ref(null)

function pct(used, budget) {
  return budget > 0 ? Math.min(100, Math.round((used / budget) * 100)) : 0
}
function regenKey() {
  usageForm.idempotency_key = 'job-' + Math.random().toString(16).slice(2, 10)
}

async function load() {
  loading.value = true
  try {
    const [a, r, u] = await Promise.all([
      api.get('/quota/accounts'), api.get('/quota/reservations'), api.get('/quota/usage'),
    ])
    accounts.value = a.data
    reservations.value = r.data
    usageEvents.value = u.data
    if (!acqProject.value && a.data.length) acqProject.value = a.data[0].project_id
    if (!usageForm.project_id && a.data.length) usageForm.project_id = a.data[0].project_id
  } finally {
    loading.value = false
  }
}

async function acquire() {
  try {
    await api.post('/quota/reservations', { project_id: acqProject.value, kind: '查询' })
    ElMessage.success('已占用一个并发槽')
  } catch { /* 409 提示已由拦截器弹出 */ }
  await load()
}

async function release(row) {
  await api.post(`/quota/reservations/${row.id}/release`)
  await load()
}

async function report(retry) {
  if (retry) usageForm.idempotency_key = lastKey.value
  const { data } = await api.post('/quota/usage', { ...usageForm })
  reportResult.value = data
  lastKey.value = usageForm.idempotency_key
  lookupKey.value = usageForm.idempotency_key
  if (!retry) regenKey()
  await load()
}

async function lookup() {
  if (!lookupKey.value) return
  receipts.value = (await api.get(`/quota/usage/by-key/${lookupKey.value}/receipts`)).data
}

onMounted(() => {
  regenKey()
  load()
})
</script>
