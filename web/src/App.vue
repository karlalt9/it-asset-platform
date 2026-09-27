<template>
  <el-container class="layout">
    <el-aside width="210px" class="sidebar">
      <div class="brand">
        <div class="brand-title">IT 资产巡检平台</div>
        <div class="brand-sub">Asset &amp; Health Center</div>
      </div>
      <el-menu :default-active="activePath" router class="menu">
        <el-menu-item index="/">总览</el-menu-item>
        <el-menu-item index="/devices">设备资产</el-menu-item>
        <el-menu-item index="/alerts">告警中心</el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <span class="header-title">{{ currentTitle }}</span>
        <span class="header-right">
          <el-link href="/docs" target="_blank" type="primary">接口文档</el-link>
        </span>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>

  <div v-if="needAuth" class="auth-mask">
    <div class="auth-card">
      <h3 class="auth-title">需要读取令牌</h3>
      <p class="auth-desc">
        这个看板需要凭证才能查看数据。令牌显示在服务端启动窗口里，
        也配置在项目根目录 <span class="mono">.env</span> 文件的
        <span class="mono">IAP_READ_TOKEN</span> 一项。
      </p>
      <el-input
        v-model="tokenInput"
        placeholder="请输入读取令牌"
        show-password
        @keyup.enter="submit"
      />
      <el-button type="primary" :disabled="!tokenInput.trim()" @click="submit">
        进入看板
      </el-button>
      <p v-if="errorText" class="auth-error">{{ errorText }}</p>
    </div>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'

import { api } from './api'
import { clearReadToken, needAuth, setReadToken } from './auth'

const route = useRoute()

const tokenInput = ref('')
const errorText = ref('')

const activePath = computed(() => {
  if (route.path.startsWith('/devices')) return '/devices'
  return route.path
})

const currentTitle = computed(() => route.meta.title || '总览')

async function submit() {
  const value = tokenInput.value.trim()
  if (!value) return

  errorText.value = ''
  setReadToken(value)

  try {
    // 用一个真实请求验证令牌是否正确
    await api.overview()
    window.location.reload()
  } catch (error) {
    errorText.value = '令牌不正确，请检查后重试'
    clearReadToken()
    ElMessage.error('令牌不正确')
  }
}
</script>

<style scoped>
.layout {
  min-height: 100vh;
}

.sidebar {
  background: #1f2d3d;
  color: #fff;
}

.brand {
  padding: 20px 18px 16px;
  border-bottom: 1px solid #2c3e50;
}

.brand-title {
  font-size: 16px;
  font-weight: 600;
}

.brand-sub {
  margin-top: 4px;
  font-size: 11px;
  color: #8798ab;
  letter-spacing: 0.6px;
}

.menu {
  border-right: none;
  background: transparent;
}

.menu :deep(.el-menu-item) {
  color: #c0ccda;
}

.menu :deep(.el-menu-item:hover) {
  background: #2c3e50;
  color: #fff;
}

.menu :deep(.el-menu-item.is-active) {
  background: #2c3e50;
  color: #fff;
  border-left: 3px solid #409eff;
}

.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}

.header-title {
  font-size: 15px;
  font-weight: 600;
}

.main {
  padding: 0;
  background: #f4f6f9;
}

.auth-mask {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(31, 45, 61, 0.55);
}

.auth-card {
  width: 380px;
  padding: 26px 28px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.22);
}

.auth-title {
  margin: 0 0 10px;
  font-size: 17px;
}

.auth-desc {
  margin: 0 0 16px;
  color: #8492a6;
  font-size: 13px;
  line-height: 1.7;
}

.auth-card :deep(.el-button) {
  width: 100%;
  margin-top: 14px;
}

.auth-error {
  margin: 10px 0 0;
  color: #f56c6c;
  font-size: 13px;
}
</style>
