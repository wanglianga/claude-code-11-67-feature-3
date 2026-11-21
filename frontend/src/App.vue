<template>
  <router-view v-if="$route.meta.public" />
  <el-container v-else class="layout">
    <el-aside width="230px">
      <div class="brand">
        <div class="brand-title">科研数据工作台</div>
        <div class="brand-sub">产品目录 · 资格开通 · 质量认证 · 额度 · 审计</div>
      </div>
      <el-menu :default-active="$route.path" router background-color="#0f2740" text-color="#b8c7d9"
        active-text-color="#ffffff">
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <span>{{ m.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <span class="page-title">{{ $route.meta.title || '' }}</span>
        <div class="user-box">
          <el-tag size="small" effect="plain">{{ roleLabel }}</el-tag>
          <span class="username">{{ user?.display_name }}</span>
          <el-button size="small" text @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { currentUser } from './api'

const router = useRouter()
const user = computed(() => currentUser()).value

const allMenus = [
  { path: '/catalog', title: '产品目录', roles: ['ADMIN', 'PI', 'ANALYST', 'AUDITOR'] },
  { path: '/projects', title: '课题档案', roles: ['ADMIN', 'PI', 'ANALYST', 'AUDITOR'] },
  { path: '/workbench', title: '资格开通工作台', roles: ['ADMIN', 'PI', 'ANALYST', 'AUDITOR'] },
  { path: '/quality', title: '批次质量认证', roles: ['ADMIN', 'PI', 'ANALYST', 'AUDITOR'] },
  { path: '/access', title: '数据访问模拟', roles: ['PI', 'ANALYST'] },
  { path: '/quota', title: '额度账本', roles: ['ADMIN', 'PI', 'ANALYST', 'AUDITOR'] },
  { path: '/audit', title: '审计查询', roles: ['ADMIN', 'AUDITOR'] },
]
const menus = allMenus.filter((m) => !user || m.roles.includes(user.role))

const roleLabel = { ADMIN: '治理管理员', PI: '课题负责人', ANALYST: '数据分析师', AUDITOR: '审计员' }[user?.role] || user?.role

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  router.push('/login')
}
</script>

<style>
body { margin: 0; font-family: 'Helvetica Neue', 'PingFang SC', 'Microsoft YaHei', sans-serif; }
.layout { height: 100vh; }
.el-aside { background: #0f2740; }
.brand { padding: 18px 16px; color: #fff; border-bottom: 1px solid rgba(255, 255, 255, 0.08); }
.brand-title { font-size: 16px; font-weight: 600; }
.brand-sub { font-size: 11px; color: #7f97ad; margin-top: 4px; }
.el-menu { border-right: none; }
.header { display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid #e8ecf1; background: #fff; }
.page-title { font-size: 15px; font-weight: 600; color: #1f2d3d; }
.user-box { display: flex; align-items: center; gap: 10px; }
.username { font-size: 13px; color: #333; }
.el-main { background: #f4f6f9; }
</style>
