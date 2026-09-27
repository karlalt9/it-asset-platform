<template>
  <div class="page">
    <h2 class="page-title">总览</h2>
    <p class="page-subtitle">
      数据来自终端最近一次巡检上报，最后更新时间 {{ formatTime(data.generated_at) }}
    </p>

    <div class="stat-grid">
      <div class="stat-card">
        <div class="stat-label">设备总数</div>
        <div class="stat-value">{{ data.device_total }}</div>
        <div class="stat-hint">已纳入集中管理的终端</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">在线设备</div>
        <div class="stat-value" style="color: #67c23a">{{ data.device_online }}</div>
        <div class="stat-hint">近期有正常上报</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">离线设备</div>
        <div class="stat-value" :style="{ color: data.device_offline > 0 ? '#e6a23c' : '#303133' }">
          {{ data.device_offline }}
        </div>
        <div class="stat-hint">超过阈值没有上报，需要确认</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">未处理告警</div>
        <div class="stat-value" :style="{ color: data.alert_open > 0 ? '#f56c6c' : '#303133' }">
          {{ data.alert_open }}
        </div>
        <div class="stat-hint">
          严重 {{ data.alert_open_by_level.critical || 0 }} 条，警告
          {{ data.alert_open_by_level.warning || 0 }} 条
        </div>
      </div>
    </div>

    <div class="panel-grid">
      <div class="panel">
        <h3 class="panel-title">近 7 天新增告警趋势</h3>
        <ChartBox :option="trendOption" />
      </div>
      <div class="panel">
        <h3 class="panel-title">未处理告警等级分布</h3>
        <ChartBox :option="levelOption" />
      </div>
    </div>

    <p class="page-subtitle" style="margin-top: 16px">
      当前加载了 {{ data.rule_count }} 条阈值规则，规则文件位于
      <span class="mono">server/config/rules.json</span>
    </p>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { api, formatDay, formatTime, levelLabel } from '../api'
import ChartBox from '../components/ChartBox.vue'

const data = ref({
  device_total: 0,
  device_online: 0,
  device_offline: 0,
  alert_open: 0,
  alert_open_by_level: {},
  alert_trend: [],
  rule_count: 0,
  generated_at: null,
})

const LEVEL_COLOR = {
  critical: '#f56c6c',
  warning: '#e6a23c',
  notice: '#909399',
  info: '#67c23a',
}

const trendOption = computed(() => ({
  tooltip: { trigger: 'axis' },
  legend: { bottom: 0, data: ['严重', '警告', '注意', '提示'] },
  grid: { left: 44, right: 20, top: 24, bottom: 48 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: data.value.alert_trend.map((point) => formatDay(point.date)),
  },
  yAxis: { type: 'value', minInterval: 1 },
  series: ['critical', 'warning', 'notice', 'info'].map((level) => ({
    name: levelLabel(level),
    type: 'line',
    smooth: true,
    symbolSize: 6,
    itemStyle: { color: LEVEL_COLOR[level] },
    data: data.value.alert_trend.map((point) => point[level] || 0),
  })),
}))

const levelOption = computed(() => {
  const entries = Object.entries(data.value.alert_open_by_level || {}).filter(
    ([, value]) => value > 0,
  )
  return {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        avoidLabelOverlap: true,
        label: { formatter: '{b}: {c}' },
        data: entries.map(([level, value]) => ({
          name: levelLabel(level),
          value,
          itemStyle: { color: LEVEL_COLOR[level] },
        })),
      },
    ],
  }
})

async function load() {
  try {
    data.value = await api.overview()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

onMounted(load)
</script>
