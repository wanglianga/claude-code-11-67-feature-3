<template>
  <div>
    <el-row :gutter="14">
      <el-col :span="8">
        <el-card shadow="never">
          <template #header><b>访问事件（点击回查）</b></template>
          <el-table :data="events" size="small" v-loading="loading" @row-click="inspect" row-class-name="clickable"
            max-height="640">
            <el-table-column prop="id" label="ID" width="55" />
            <el-table-column prop="created_at" label="时间" width="160" />
            <el-table-column prop="member_name" label="成员" width="75" />
            <el-table-column prop="purpose_code" label="用途" width="75" />
            <el-table-column label="状态" width="65">
              <template #default="{ row }">
                <el-tag :type="row.status === '成功' ? 'success' : 'danger'" size="small">{{ row.status }}</el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="16">
        <template v-if="audit">
          <el-card shadow="never">
            <template #header>
              <div style="display: flex; gap: 10px; align-items: center">
                <b>访问事件 #{{ audit.event.id }} 还原</b>
                <el-tag :type="audit.event.status === '成功' ? 'success' : 'danger'" size="small">
                  {{ audit.event.status }}
                </el-tag>
                <span class="muted">{{ audit.event.created_at }}｜{{ audit.event.member_name }}｜{{ audit.event.kind }}</span>
              </div>
            </template>
            <el-alert v-if="audit.event.deny_reason" type="error" :closable="false"
              :title="`拒绝原因：${audit.event.deny_reason}`" style="margin-bottom: 10px" />
            <el-descriptions :column="2" border size="small">
              <el-descriptions-item label="请求号">{{ audit.event.request_id }}</el-descriptions-item>
              <el-descriptions-item label="资格实例">
                #{{ audit.event.qualification_id || '—' }}
                <el-tag v-if="audit.qualification_now" size="small"
                  :type="audit.qualification_now.status === '已签发' ? 'success' : 'info'">
                  当前{{ audit.qualification_now.status }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="放行字段数">{{ audit.event.granted_fields.length }}</el-descriptions-item>
              <el-descriptions-item label="用途">{{ audit.event.purpose_code }}</el-descriptions-item>
            </el-descriptions>
          </el-card>

          <el-card shadow="never" style="margin-top: 12px">
            <template #header><b>① 当时的产品定义（快照 vs 当前目录）</b></template>
            <el-descriptions :column="3" border size="small" style="margin-bottom: 8px">
              <el-descriptions-item label="产品">{{ audit.product_then.code }} {{ audit.product_then.name }}</el-descriptions-item>
              <el-descriptions-item label="当时目录版本">v{{ audit.product_then.catalog_version }}</el-descriptions-item>
              <el-descriptions-item label="当前目录版本">v{{ audit.product_now?.catalog_version }}</el-descriptions-item>
            </el-descriptions>
            <el-alert v-if="!audit.catalog_diff.length" type="success" :closable="false"
              title="目录定义与访问当时一致，无差异" />
            <el-table v-else :data="audit.catalog_diff" size="small" border>
              <el-table-column prop="field_name" label="字段" width="150" />
              <el-table-column prop="change" label="当时 → 现在的变化" min-width="260" />
            </el-table>
            <el-collapse style="margin-top: 8px">
              <el-collapse-item :title="`当时快照字段清单（${audit.product_then.fields?.length || 0} 个）`">
                <el-table :data="audit.product_then.fields" size="small" max-height="240">
                  <el-table-column prop="field_name" label="字段名" width="130" />
                  <el-table-column prop="semantic" label="语义" min-width="160" />
                  <el-table-column label="等级" width="60">
                    <template #default="{ row }">L{{ row.sensitivity_level }}</template>
                  </el-table-column>
                  <el-table-column label="可用期" width="200">
                    <template #default="{ row }">{{ row.available_from }} ~ {{ row.available_to }}</template>
                  </el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>
          </el-card>

          <el-card shadow="never" style="margin-top: 12px">
            <template #header><b>② 当时的资格依据</b></template>
            <template v-if="audit.qualification_basis_then?.basis">
              <el-descriptions :column="1" border size="small">
                <el-descriptions-item label="求交规则">
                  {{ audit.qualification_basis_then.basis.rule }}
                </el-descriptions-item>
                <el-descriptions-item label="伦理批件">
                  <div v-for="e in audit.qualification_basis_then.basis.ethics" :key="e.approval_no">
                    {{ e.approval_no }}｜{{ e.scope_subjects }}｜上限 L{{ e.max_sensitivity_level }}｜
                    {{ e.valid_from }} ~ {{ e.valid_to }}（{{ e.status }}）
                  </div>
                </el-descriptions-item>
                <el-descriptions-item label="用途条件">
                  ≤L{{ audit.qualification_basis_then.basis.purpose.max_sensitivity_level }}｜禁用：
                  {{ audit.qualification_basis_then.basis.purpose.forbidden_tags.join('、') || '无' }}｜导出：
                  {{ audit.qualification_basis_then.basis.purpose.export_allowed ? '允许' : '禁止' }}
                </el-descriptions-item>
                <el-descriptions-item label="资格有效期">
                  {{ audit.qualification_basis_then.valid_from }} ~ {{ audit.qualification_basis_then.valid_to }}
                </el-descriptions-item>
                <el-descriptions-item label="覆盖成员">
                  {{ audit.qualification_basis_then.basis.covered_members.map((m) => `${m.name}(${m.role})`).join('、') }}
                </el-descriptions-item>
              </el-descriptions>
            </template>
            <el-alert v-else type="info" :closable="false" title="该次访问未命中资格实例（拒绝事件）" />
          </el-card>

          <el-card shadow="never" style="margin-top: 12px">
            <template #header><b>③ 当时的额度变化</b></template>
            <template v-if="audit.quota_trail.usage_event">
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="并发占用">
                  #{{ audit.quota_trail.reservation?.id }}（{{ audit.quota_trail.reservation?.status }}）
                </el-descriptions-item>
                <el-descriptions-item label="回执号">{{ audit.quota_trail.usage_event.receipt_no }}</el-descriptions-item>
                <el-descriptions-item label="消耗">
                  {{ audit.quota_trail.usage_event.kind }} × {{ audit.quota_trail.usage_event.amount }}
                </el-descriptions-item>
                <el-descriptions-item label="幂等键">{{ audit.quota_trail.usage_event.idempotency_key }}</el-descriptions-item>
                <el-descriptions-item label="扣减后查询余额" :span="2">
                  {{ audit.quota_trail.usage_event.balance_after.used_query }} /
                  {{ audit.quota_trail.usage_event.balance_after.budget_query }}
                </el-descriptions-item>
              </el-descriptions>
              <el-table :data="audit.quota_trail.usage_reports" size="small" style="margin-top: 8px">
                <el-table-column prop="reported_at" label="上报时间" width="170" />
                <el-table-column label="类型" width="100">
                  <template #default="{ row }">
                    <el-tag :type="row.is_duplicate ? 'warning' : 'success'" size="small">
                      {{ row.is_duplicate ? '重复回执' : '首次' }}
                    </el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="note" label="备注" min-width="180" />
              </el-table>
            </template>
            <el-alert v-else type="info" :closable="false" title="该次访问未产生额度消耗" />
          </el-card>
        </template>
        <el-empty v-else description="选择左侧一条访问事件开始回查" />
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import api from '../api'

const events = ref([])
const audit = ref(null)
const loading = ref(false)

async function inspect(row) {
  audit.value = (await api.get(`/audit/access/${row.id}`)).data
}

onMounted(async () => {
  loading.value = true
  try {
    events.value = (await api.get('/access/events')).data
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.muted { color: #909399; font-size: 12px; }
</style>
