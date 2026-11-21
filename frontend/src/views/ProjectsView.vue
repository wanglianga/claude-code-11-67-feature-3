<template>
  <div>
    <el-card shadow="never">
      <el-table :data="projects" v-loading="loading" @row-click="openDetail" row-class-name="clickable">
        <el-table-column prop="code" label="课题编号" width="110" />
        <el-table-column prop="name" label="课题名称" min-width="180" />
        <el-table-column prop="pi_name" label="负责人" width="100" />
        <el-table-column label="课题期限" width="210">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === '在研' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="drawer" :title="`${detail?.name || ''}（${detail?.code || ''}）`" size="62%">
      <template v-if="detail">
        <h4>研究目的与用途条件</h4>
        <el-table :data="detail.purposes" size="small" border>
          <el-table-column prop="purpose_code" label="用途编码" width="110" />
          <el-table-column prop="description" label="说明" min-width="230" />
          <el-table-column label="敏感上限" width="90">
            <template #default="{ row }">L{{ row.max_sensitivity_level }}</template>
          </el-table-column>
          <el-table-column label="禁用标签" width="170">
            <template #default="{ row }">
              <el-tag v-for="t in row.forbidden_tags" :key="t" size="small" type="danger" style="margin-right: 4px">{{ t }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="允许导出" width="80">
            <template #default="{ row }">{{ row.export_allowed ? '是' : '否' }}</template>
          </el-table-column>
        </el-table>

        <h4>成员与角色</h4>
        <el-table :data="detail.members" size="small" border>
          <el-table-column prop="name" label="姓名" width="110" />
          <el-table-column prop="role" label="角色" width="110" />
          <el-table-column label="任期" width="210">
            <template #default="{ row }">{{ row.valid_from }} ~ {{ row.valid_to }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === '在职' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
        </el-table>

        <h4>伦理批件</h4>
        <el-table :data="detail.ethics" size="small" border>
          <el-table-column prop="approval_no" label="批件号" width="130" />
          <el-table-column prop="scope_subjects" label="适用对象" min-width="180" />
          <el-table-column label="允许用途" width="140">
            <template #default="{ row }">{{ row.allowed_purposes.join('、') }}</template>
          </el-table-column>
          <el-table-column label="敏感上限" width="80">
            <template #default="{ row }">L{{ row.max_sensitivity_level }}</template>
          </el-table-column>
          <el-table-column label="有效期" width="200">
            <template #default="{ row }">{{ row.valid_from }} ~ {{ row.valid_to }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.status === '有效' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-if="isAdmin" label="操作" width="110">
            <template #default="{ row }">
              <el-button v-if="row.status === '有效'" size="small" text type="danger"
                @click="revokeEthics(row)">标记失效</el-button>
              <el-button v-else size="small" text type="primary" @click="restoreEthics(row)">恢复有效</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-alert v-if="isAdmin" type="info" :closable="false" style="margin-top: 10px"
          title="批件失效后：新资格编译将拒绝（批次中未完成项不得签发）；已签发实例状态独立，需在资格开通工作台单独撤回。" />
      </template>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api, { currentUser } from '../api'

const projects = ref([])
const detail = ref(null)
const drawer = ref(false)
const loading = ref(false)
const isAdmin = computed(() => currentUser()?.role === 'ADMIN')

async function load() {
  loading.value = true
  try {
    projects.value = (await api.get('/projects')).data
  } finally {
    loading.value = false
  }
}

async function openDetail(row) {
  detail.value = (await api.get(`/projects/${row.id}`)).data
  drawer.value = true
}

async function revokeEthics(row) {
  const { value } = await ElMessageBox.prompt('请输入失效原因', '标记伦理批件失效', {
    inputValue: '委员会审查未通过',
  })
  await api.post(`/projects/${detail.value.id}/ethics/${row.id}/revoke`, { reason: value || '' })
  ElMessage.warning('批件已失效，后续资格编译将拒绝')
  await openDetail(detail.value)
}

async function restoreEthics(row) {
  await api.post(`/projects/${detail.value.id}/ethics/${row.id}/restore`)
  ElMessage.success('批件已恢复有效')
  await openDetail(detail.value)
}

onMounted(load)
</script>
