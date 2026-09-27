<template>
  <div ref="container" :class="['chart', short ? 'chart-short' : '']"></div>
</template>

<script setup>
import * as echarts from 'echarts'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  option: { type: Object, required: true },
  short: { type: Boolean, default: false },
})

const container = ref(null)
let chart = null

function resize() {
  if (chart) chart.resize()
}

function render() {
  if (chart) chart.setOption(props.option, true)
}

onMounted(() => {
  chart = echarts.init(container.value)
  render()
  window.addEventListener('resize', resize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  if (chart) {
    chart.dispose()
    chart = null
  }
})

watch(() => props.option, render, { deep: true })
</script>
