<template>
  <div class="page">
    <h2 class="page-title">设备资产</h2>
    <p class="page-subtitle">共 {{ total }} 台设备。点击主机名查看详情，也可以导出资产清单。</p>

    <div class="toolbar">
      <el-input
        v-model="filters.keyword"
        placeholder="搜索主机名 / 使用人 / 部门"
        clearable
        style="width: 260px"
        @keyup.enter="reload"
      />
      <el-select v-model="filters.status" placeholder="在线状态" clearable style="width: 140px">
        <el-option label="在线" value="online" />
        <el-option label="离线" value="offline" />
      </el-select>
      <el-button type="primary" @click="reload">查询</el-button>
      <el-button @click="reset">重置</el-button>
      <div class="toolbar-spacer"></div>
      <el-button @click="exportCsv">导出 CSV</el-button>
    </div>

    <el-table v-loading="loading" :data="items" border stripe>
      <el-table-column prop="hostname" label="主机名" min-width="150">
        <template #default="{ row }">
          <span class="clickable" @click="openDetail(row.id)">{{ row.hostname }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.status === 'online' ? 'success' : 'info'" size="small">
            {{ row.status === 'online' ? '在线' : '离线' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="owner" label="使用人" width="100">
        <template #default="{ row }">{{ row.owner || '-' }}</template>
      </el-table-column>
      <el-table-column prop="department" label="部门" width="110">
        <template #default="{ row }">{{ row.department || '-' }}</template>
      </el-table-column>
      <el-table-column prop="os_name" label="操作系统" min-width="200" show-overflow-tooltip />
      <el-table-column prop="cpu_model" label="处理器" min-width="200" show-overflow-tooltip />
      <el-table-column label="内存" width="90">
        <template #default="{ row }">
          {{ row.ram_total_gb ? `${row.ram_total_gb} GB` : '-' }}
        </template>
      </el-table-column>
      <el-table-column label="最近上报" width="170">
        <template #default="{ row }">{{ formatTime(row.last_seen) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="90" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" @click="removeDevice(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        @current-change="load"
        @size-change="reload"
      />
    </div>
  </div>
</template>

<script setup>
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, formatTime } from '../api'

const router = useRouter()

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const filters = reactive({ keyword: '', status: '' })

async function load() {
  loading.value = true
  try {
    const data = await api.devices({
      keyword: filters.keyword,
      status: filters.status,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = data.items
    total.value = data.total
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function reset() {
  filters.keyword = ''
  filters.status = ''
  reload()
}

function openDetail(id) {
  router.push({ name: 'device-detail', params: { id } })
}

async function exportCsv() {
  try {
    const blob = await api.exportCsv()
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = '设备资产清单.csv'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function removeDevice(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除设备「${row.hostname}」？它的巡检记录、指标和告警会一起删除，无法恢复。` +
        '删除后在这台机器上重新运行一次 Agent，它会重新出现在列表里。',
      '删除确认',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger',
      },
    )
  } catch {
    return
  }

  try {
    await api.deleteDevice(row.id)
    ElMessage.success('设备已删除')
    if (items.value.length === 1 && page.value > 1) {
      page.value -= 1
    }
    load()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(load)
</script>

<style scoped>
.pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
