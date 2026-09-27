<template>
  <div v-loading="loading" class="page">
    <el-button link type="primary" @click="goBack">← 返回设备列表</el-button>

    <template v-if="device">
      <h2 class="page-title">
        {{ device.hostname }}
        <el-tag
          :type="device.status === 'online' ? 'success' : 'info'"
          size="small"
          style="margin-left: 8px"
        >
          {{ device.status === 'online' ? '在线' : '离线' }}
        </el-tag>
      </h2>
      <p class="page-subtitle">
        设备指纹 <span class="mono">{{ device.fingerprint }}</span>，最近上报
        {{ formatTime(device.last_seen) }}
      </p>

      <div class="panel" style="margin-bottom: 16px">
        <div class="panel-header">
          <h3 class="panel-title">基本信息</h3>
          <el-button size="small" @click="editVisible = true">补录资产信息</el-button>
        </div>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="使用人">{{ device.owner || '-' }}</el-descriptions-item>
          <el-descriptions-item label="部门">{{ device.department || '-' }}</el-descriptions-item>
          <el-descriptions-item label="位置">{{ device.location || '-' }}</el-descriptions-item>
          <el-descriptions-item label="固态盘数量">
            {{ device.ssd_count === null ? '未读取' : `${device.ssd_count} 块` }}
          </el-descriptions-item>
          <el-descriptions-item label="操作系统">{{ device.os_name || '-' }}</el-descriptions-item>
          <el-descriptions-item label="系统架构">{{ device.architecture || '-' }}</el-descriptions-item>
          <el-descriptions-item label="处理器">{{ device.cpu_model || '-' }}</el-descriptions-item>
          <el-descriptions-item label="核心 / 线程">
            {{ device.cpu_cores || '-' }} 核 / {{ device.cpu_threads || '-' }} 线程
          </el-descriptions-item>
          <el-descriptions-item label="内存容量">
            {{ device.ram_total_gb ? `${device.ram_total_gb} GB` : '-' }}
          </el-descriptions-item>
          <el-descriptions-item label="首次纳管">{{ formatTime(device.first_seen) }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="2">{{ device.note || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>

      <div class="panel" style="margin-bottom: 16px">
        <div class="panel-header">
          <h3 class="panel-title">指标趋势（最近 7 天）</h3>
          <el-checkbox-group v-model="selectedKeys" size="small" @change="loadMetrics">
            <el-checkbox-button value="cpu.load_percent">CPU</el-checkbox-button>
            <el-checkbox-button value="memory.used_percent">内存</el-checkbox-button>
            <el-checkbox-button value="disk.used_percent">磁盘</el-checkbox-button>
          </el-checkbox-group>
        </div>
        <ChartBox v-if="series.length" :option="chartOption" />
        <el-empty v-else description="暂无指标数据" :image-size="80" />
      </div>

      <div class="panel" style="margin-bottom: 16px">
        <h3 class="panel-title">未处理告警（{{ openAlerts.length }}）</h3>
        <el-table :data="openAlerts" border size="small">
          <el-table-column label="等级" width="90">
            <template #default="{ row }">
              <el-tag :type="levelType(row.level)" size="small">{{ levelLabel(row.level) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="message" label="说明" min-width="260" />
          <el-table-column prop="rule_id" label="规则" width="200">
            <template #default="{ row }">
              <span class="mono">{{ row.rule_id }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="occurrences" label="累计次数" width="100" />
          <el-table-column label="最近命中" width="170">
            <template #default="{ row }">{{ formatTime(row.last_seen) }}</template>
          </el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <h3 class="panel-title">最近巡检记录</h3>
        <el-table :data="recentReports" border size="small">
          <el-table-column prop="report_id" label="上报编号" width="280">
            <template #default="{ row }">
              <span class="mono">{{ row.report_id }}</span>
            </template>
          </el-table-column>
          <el-table-column label="采集时间" width="170">
            <template #default="{ row }">{{ formatTime(row.collected_at) }}</template>
          </el-table-column>
          <el-table-column label="接收时间" width="170">
            <template #default="{ row }">{{ formatTime(row.received_at) }}</template>
          </el-table-column>
          <el-table-column prop="warning_count" label="警告" width="80" />
          <el-table-column prop="notice_count" label="注意" width="80" />
          <el-table-column prop="summary" label="结论" min-width="200" />
        </el-table>
      </div>
    </template>

    <el-dialog v-model="editVisible" title="补录资产信息" width="440px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="使用人"><el-input v-model="form.owner" /></el-form-item>
        <el-form-item label="部门"><el-input v-model="form.department" /></el-form-item>
        <el-form-item label="位置"><el-input v-model="form.location" /></el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.note" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, formatTime, levelLabel, parseTime } from '../api'
import ChartBox from '../components/ChartBox.vue'

const props = defineProps({ id: { type: String, required: true } })
const router = useRouter()
const deviceId = Number(props.id)

const loading = ref(false)
const device = ref(null)
const openAlerts = ref([])
const recentReports = ref([])

const series = ref([])
const selectedKeys = ref(['cpu.load_percent', 'memory.used_percent'])

const editVisible = ref(false)
const form = reactive({ owner: '', department: '', location: '', note: '' })

const PALETTE = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9c27b0']

function levelType(level) {
  return { critical: 'danger', warning: 'warning', notice: 'info', info: 'success' }[level] || 'info'
}

function seriesName(item) {
  return item.dimension ? `${item.key} ${item.dimension}` : item.key
}

const chartOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0, type: 'scroll' },
  grid: { left: 52, right: 24, top: 24, bottom: 56 },
  xAxis: { type: 'time' },
  yAxis: { type: 'value' },
  series: series.value.map((item, index) => ({
    name: seriesName(item),
    type: 'line',
    smooth: true,
    showSymbol: false,
    itemStyle: { color: PALETTE[index % PALETTE.length] },
    data: item.points
      .map((point) => {
        const date = parseTime(point.t)
        return date ? [date.getTime(), point.v] : null
      })
      .filter(Boolean),
  })),
}))

async function load() {
  loading.value = true
  try {
    const detail = await api.device(deviceId)
    device.value = detail.device
    openAlerts.value = detail.open_alerts
    recentReports.value = detail.recent_reports
    form.owner = detail.device.owner || ''
    form.department = detail.device.department || ''
    form.location = detail.device.location || ''
    form.note = detail.device.note || ''
    await loadMetrics()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    loading.value = false
  }
}

async function loadMetrics() {
  if (!selectedKeys.value.length) {
    series.value = []
    return
  }
  try {
    const data = await api.metrics(deviceId, selectedKeys.value)
    series.value = data.series
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function save() {
  try {
    device.value = await api.updateDevice(deviceId, { ...form })
    editVisible.value = false
    ElMessage.success('已保存')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function goBack() {
  router.push({ name: 'devices' })
}

onMounted(load)
</script>

<style scoped>
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.panel-header .panel-title {
  margin: 0;
}
</style>
