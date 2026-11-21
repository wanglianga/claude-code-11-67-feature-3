<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2>科研数据产品目录与资格开通工作台</h2>
      <p class="tip">医学研究中心 · 演示环境（数据均为虚构）</p>
      <el-form :model="form" @keyup.enter="doLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" show-password />
        </el-form-item>
        <el-button type="primary" style="width: 100%" :loading="loading" @click="doLogin">登录</el-button>
      </el-form>
      <el-divider content-position="left">测试账号</el-divider>
      <div class="accounts">
        <div v-for="a in accounts" :key="a.u" class="acc" @click="fill(a)">
          <el-tag size="small">{{ a.role }}</el-tag> {{ a.u }} / {{ a.p }}
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const router = useRouter()
const form = reactive({ username: 'admin', password: 'admin123' })
const loading = ref(false)
const accounts = [
  { u: 'admin', p: 'admin123', role: '治理管理员' },
  { u: 'wangjianguo', p: 'wang123', role: '课题负责人' },
  { u: 'zhangmin', p: 'zhang123', role: '分析师(跨课题)' },
  { u: 'zhaolei', p: 'zhao123', role: '分析师(统计师)' },
  { u: 'auditor', p: 'audit123', role: '审计员' },
]

function fill(a) {
  form.username = a.u
  form.password = a.p
}

async function doLogin() {
  loading.value = true
  try {
    const { data } = await api.post('/auth/login', form)
    localStorage.setItem('token', data.token)
    localStorage.setItem('user', JSON.stringify(data.user))
    router.push('/catalog')
  } catch {
    ElMessage.error('用户名或密码错误')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page { height: 100vh; display: flex; align-items: center; justify-content: center; background: linear-gradient(135deg, #0f2740, #1c4b7a); }
.login-card { width: 420px; }
h2 { margin: 0 0 4px; font-size: 18px; }
.tip { color: #909399; font-size: 12px; margin: 0 0 18px; }
.accounts { font-size: 12px; color: #606266; }
.acc { padding: 4px 0; cursor: pointer; }
.acc:hover { color: #1c4b7a; }
</style>
