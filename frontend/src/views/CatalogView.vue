<template>
  <div>
    <el-card shadow="never">
      <el-table :data="products" v-loading="loading" @row-click="openDetail" row-class-name="clickable">
        <el-table-column prop="code" label="产品编码" width="110" />
        <el-table-column prop="name" label="产品名称" min-width="170" />
        <el-table-column prop="source_system" label="来源系统" width="140" />
        <el-table-column prop="update_frequency" label="更新频率" width="90" />
        <el-table-column prop="owner_dept" label="责任科室" width="110" />
        <el-table-column prop="field_count" label="字段数" width="80" />
        <el-table-column label="目录版本" width="90">
          <template #default="{ row }">v{{ row.catalog_version }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === '上架' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="drawer" :title="`${detail?.name || ''}（${detail?.code || ''}）`" size="62%">
      <template v-if="detail">
        <el-descriptions :column="3" border size="small" style="margin-bottom: 14px">
          <el-descriptions-item label="来源系统">{{ detail.source_system }}</el-descriptions-item>
          <el-descriptions-item label="更新频率">{{ detail.update_frequency }}</el-descriptions-item>
          <el-descriptions-item label="目录版本">v{{ detail.catalog_version }}</el-descriptions-item>
          <el-descriptions-item label="说明" :span="3">{{ detail.description }}</el-descriptions-item>
        </el-descriptions>
        <h4>字段清单（语义 / 敏感等级 / 可用时间范围）</h4>
        <el-table :data="detail.fields" size="small" border>
          <el-table-column prop="field_name" label="字段名" width="130" />
          <el-table-column prop="semantic" label="字段语义" min-width="180" />
          <el-table-column label="敏感等级" width="110">
            <template #default="{ row }">
              <el-tag :type="levelType(row.sensitivity_level)" size="small">L{{ row.sensitivity_level }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="标签" width="130">
            <template #default="{ row }">
              <el-tag v-for="t in row.tags" :key="t" size="small" type="warning" style="margin-right: 4px">{{ t }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="可用时间范围" width="200">
            <template #default="{ row }">{{ row.available_from }} ~ {{ row.available_to }}</template>
          </el-table-column>
          <el-table-column label="状态" width="70">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '在用' : '停用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="isAdmin" label="操作" width="80">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="editField(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-collapse style="margin-top: 14px">
          <el-collapse-item title="目录变更日志" name="1">
            <el-table :data="changes" size="small">
              <el-table-column prop="created_at" label="时间" width="170" />
              <el-table-column prop="change_type" label="类型" width="90" />
              <el-table-column label="内容" min-width="260">
                <template #default="{ row }">{{ formatChange(row.detail) }}</template>
              </el-table-column>
              <el-table-column prop="actor" label="操作人" width="100" />
            </el-table>
          </el-collapse-item>
        </el-collapse>
      </template>
    </el-drawer>

    <el-dialog v-model="editDlg" :title="`编辑字段：${editing?.field_name || ''}`" width="480px">
      <el-form v-if="editing" label-width="110px">
        <el-form-item label="敏感等级">
          <el-select v-model="editing.sensitivity_level">
            <el-option v-for="l in [1, 2, 3, 4]" :key="l" :value="l" :label="`L${l}`" />
          </el-select>
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="editing.tags" multiple allow-create filterable default-first-option>
            <el-option v-for="t in ['直接标识符', '准标识符', '遗传信息']" :key="t" :value="t" :label="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="可用起始">
          <el-date-picker v-model="editing.available_from" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="可用截止">
          <el-date-picker v-model="editing.available_to" type="date" value-format="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="是否在用">
          <el-switch v-model="editing.is_active" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDlg = false">取消</el-button>
        <el-button type="primary" @click="saveField">保存（目录版本 +1）</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import api, { currentUser } from '../api'

const products = ref([])
const detail = ref(null)
const changes = ref([])
const drawer = ref(false)
const loading = ref(false)
const editDlg = ref(false)
const editing = ref(null)
const isAdmin = computed(() => currentUser()?.role === 'ADMIN')

function levelType(l) {
  return { 1: 'success', 2: 'primary', 3: 'warning', 4: 'danger' }[l] || 'info'
}

function formatChange(d) {
  const parts = []
  for (const [k, v] of Object.entries(d.changes || {})) {
    parts.push(`${k}: ${JSON.stringify(v.old)} → ${JSON.stringify(v.new)}`)
  }
  return `${d.field_name}｜${parts.join('；')}（目录 v${d.catalog_version}）`
}

async function load() {
  loading.value = true
  try {
    products.value = (await api.get('/catalog/products')).data
  } finally {
    loading.value = false
  }
}

async function openDetail(row) {
  detail.value = (await api.get(`/catalog/products/${row.id}`)).data
  changes.value = (await api.get(`/catalog/products/${row.id}/changes`)).data
  drawer.value = true
}

function editField(row) {
  editing.value = { ...row }
  editDlg.value = true
}

async function saveField() {
  const f = editing.value
  await api.put(`/catalog/products/${detail.value.id}/fields/${f.id}`, {
    sensitivity_level: f.sensitivity_level,
    tags: f.tags,
    available_from: f.available_from,
    available_to: f.available_to,
    is_active: f.is_active,
  })
  ElMessage.success('已保存，目录版本已递增；既有资格实例的投影快照不受影响')
  editDlg.value = false
  await openDetail(detail.value)
  await load()
}

onMounted(load)
</script>

<style>
.clickable { cursor: pointer; }
h4 { margin: 10px 0; }
</style>
