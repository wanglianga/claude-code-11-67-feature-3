<template>
  <div>
    <el-row :gutter="14">
      <el-col :span="9">
        <el-card shadow="never">
          <template #header><b>发起数据访问</b></template>
          <el-form label-width="90px" size="small">
            <el-form-item label="课题">
              <el-select v-model="form.project_id" @change="onProject">
                <el-option v-for="p in projects" :key="p.id" :value="p.id" :label="`${p.code} ${p.name}`" />
              </el-select>
            </el-form-item>
            <el-form-item label="产品">
              <el-select v-model="form.product_id" @change="onProduct">
                <el-option v-for="p in products" :key="p.id" :value="p.id" :label="`${p.code} ${p.name}`" />
              </el-select>
            </el-form-item>
            <el-form-item label="用途">
              <el-select v-model="form.purpose_code">
                <el-option v-for="u in purposes" :key="u.purpose_code" :value="u.purpose_code"
                  :label="`${u.purpose_code}（≤L${u.max_sensitivity_level}）`" />
              </el-select>
            </el-form-item>
            <el-form-item label="方式">
              <el-radio-group v-model="form.kind">
                <el-radio value="查询">查询</el-radio>
                <el-radio value="导出">导出</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="form.kind === '导出'" label="导出行数">
              <el-input-number v-model="form.export_rows" :min="1" :max="50000" />
            </el-form-item>
            <el-form-item label="申请字段">
              <el-select v-model="form.requested_fields" multiple collapse-tags placeholder="留空 = 申请投影内全部字段">
                <el-option v-for="f in productFields" :key="f.field_name" :value="f.field_name"
                  :label="`${f.field_name}（L${f.sensitivity_level} ${f.semantic}）`" />
              </el-select>
            </el-form-item>
            <el-form-item label="请求号">
              <el-input v-model="form.request_id">
                <template #append>
                  <el-button @click="regen">换</el-button>
                </template>
              </el-input>
            </el-form-item>
            <el-button type="primary" :loading="running" @click="run(false)">执行访问</el-button>
            <el-button :disabled="!lastRequestId" @click="run(true)">用同一请求号重试（模拟断线重发）</el-button>
          </el-form>
          <el-alert type="info" :closable="false" style="margin-top: 10px"
            title="一次访问只绑定一个用途的资格实例；不同课题/用途的字段绝不取并集。" />
        </el-card>
      </el-col>

      <el-col :span="15">
        <el-card shadow="never" v-if="result">
          <template #header>
            <div style="display: flex; gap: 10px; align-items: center">
              <b>访问结果 #{{ result.event.id }}</b>
              <el-tag :type="result.event.status === '成功' ? 'success' : 'danger'">
                {{ result.event.status }}
              </el-tag>
              <el-tag v-if="result.idempotent_replay" type="warning">幂等重放：未重复扣减额度</el-tag>
            </div>
          </template>
          <el-alert v-if="result.event.status === '拒绝'" type="error" :closable="false"
            :title="result.event.deny_reason" style="margin-bottom: 10px" />
          <template v-else>
            <el-descriptions :column="2" size="small" border style="margin-bottom: 10px">
              <el-descriptions-item label="用途">{{ result.event.purpose_code }}</el-descriptions-item>
              <el-descriptions-item label="资格实例">#{{ result.event.qualification_id }}</el-descriptions-item>
              <el-descriptions-item label="回执号">{{ result.event.quota_snapshot.receipt_no }}</el-descriptions-item>
              <el-descriptions-item label="消耗">
                {{ result.event.quota_snapshot.consumed?.kind }} × {{ result.event.quota_snapshot.consumed?.amount }}
              </el-descriptions-item>
            </el-descriptions>
            <h4>放行字段（{{ result.event.granted_fields.length }}）</h4>
            <el-table :data="result.event.granted_fields" size="small" border max-height="260">
              <el-table-column prop="field_name" label="字段名" width="130" />
              <el-table-column prop="semantic" label="语义" min-width="160" />
              <el-table-column label="等级" width="60">
                <template #default="{ row }">L{{ row.sensitivity_level }}</template>
              </el-table-column>
              <el-table-column label="有效窗口" width="200">
                <template #default="{ row }">{{ row.window_from }} ~ {{ row.window_to }}</template>
              </el-table-column>
            </el-table>
            <el-alert v-if="result.event.quota_snapshot.rejected_fields?.length" type="warning"
              :closable="false" style="margin-top: 8px"
              :title="`越界字段已拒绝：${result.event.quota_snapshot.rejected_fields.join('、')}`" />
          </template>
        </el-card>

        <el-card shadow="never" style="margin-top: 14px">
          <template #header><b>近期访问事件</b></template>
          <el-table :data="events" size="small">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="created_at" label="时间" width="165" />
            <el-table-column prop="member_name" label="成员" width="80" />
            <el-table-column prop="purpose_code" label="用途" width="80" />
            <el-table-column prop="kind" label="方式" width="60" />
            <el-table-column label="状态" width="70">
              <template #default="{ row }">
                <el-tag :type="row.status === '成功' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="deny_reason" label="拒绝原因" min-width="180">
              <template #default="{ row }">{{ row.deny_reason || '—' }}</template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import api from '../api'

const projects = ref([])
const products = ref([])
const purposes = ref([])
const productFields = ref([])
const events = ref([])
const result = ref(null)
const running = ref(false)
const lastRequestId = ref('')
const form = reactive({
  project_id: null, product_id: null, purpose_code: '', kind: '查询',
  requested_fields: [], request_id: '', export_rows: 100,
})

function regen() {
  form.request_id = 'req-' + Math.random().toString(16).slice(2, 10)
}

async function onProject() {
  const { data } = await api.get(`/projects/${form.project_id}`)
  purposes.value = data.purposes
  form.purpose_code = purposes.value[0]?.purpose_code || ''
}

async function onProduct() {
  const { data } = await api.get(`/catalog/products/${form.product_id}`)
  productFields.value = data.fields
  form.requested_fields = []
}

async function run(retry) {
  if (retry) form.request_id = lastRequestId.value
  running.value = true
  try {
    const { data } = await api.post('/access/query', { ...form })
    result.value = data
    lastRequestId.value = form.request_id
    if (!retry) regen()
    await loadEvents()
  } finally {
    running.value = false
  }
}

async function loadEvents() {
  events.value = (await api.get('/access/events')).data
}

onMounted(async () => {
  const [pj, pd] = await Promise.all([api.get('/projects'), api.get('/catalog/products')])
  projects.value = pj.data
  products.value = pd.data
  form.project_id = pj.data[0]?.id
  form.product_id = pd.data[0]?.id
  await Promise.all([onProject(), onProduct()])
  regen()
  await loadEvents()
})
</script>

<style scoped>
h4 { margin: 10px 0 8px; }
</style>
