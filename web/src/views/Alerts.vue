<template>
  <div class="page">
    <h2 class="page-title">告警中心</h2>
    <p class="page-subtitle">
      同一条规则持续命中只保留一条告警并累加次数；指标恢复正常后告警会自动关闭。
    </p>

    <div class="toolbar">
      <el-select v-model="filters.level" placeholder="告警等级" clearable style="width: 150px">
        <el-option label="严重" value="critical" />
        <el-option label="警告" value="warning" />
        <el-option label="注意" value="notice" />
        <el-option label="提示" value="info" />
      </el-select>
      <el-select v-model="filters.state" style="width: 150px">
        <el-option label="未处理" value="open" />
        <el-option label="已处理" value="resolved" />
        <el-option label="全部" value="all" />
      </el-select>
      <el-button type="primary" @click="reload">查询</el-button>
    </div>

    <el-table v-loading="loading" :data="items" border stripe>
      <el-table-column label="等级" width="90">
        <template #default="{ row }">
          <el-tag :type="levelType(row.level)" size="small">{{ levelLabel(row.level) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="设备" width="150">
        <template #default="{ row }">
          <span class="clickable" @click="openDevice(row.device_id)">{{ row.hostname }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="message" label="说明" min-width="280" />
      <el-table-column label="触发条件" width="190">
        <template #default="{ row }">
          <span class="mono">{{ row.metric_key }} {{ row.threshold_op }} {{ row.threshold_value }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="occurrences" label="累计" width="80" />
      <el-table-column label="最近命中" width="170">
        <template #default="{ row }">{{ formatTime(row.last_seen) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.resolved_at" type="success" size="small">
            {{ row.resolved_by === 'auto' ? '已自动恢复' : '已处理' }}
          </el-tag>
          <el-tag v-else type="danger" size="small">未处理</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="150">
        <template #default="{ row }">
          <el-button v-if="!row.resolved_at" link type="primary" @click="openResolve(row)">
            标记处理
          </el-button>
          <span v-else class="mono">{{ row.note || '-' }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @current-change="load"
        @size-change="reload"
      />
    </div>

    <el-dialog v-model="resolveVisible" title="标记告警已处理" width="460px">
      <p style="margin-top: 0; color: #606266">{{ current.message }}</p>
      <el-input
        v-model="note"
        type="textarea"
        :rows="3"
        placeholder="处理说明，例如：已清理 D 盘临时文件并确认空间恢复"
      />
      <template #footer>
        <el-button @click="resolveVisible = false">取消</el-button>
        <el-button type="primary" @click="submitResolve">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { api, formatTime, levelLabel } from '../api'

const router = useRouter()

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)

const filters = reactive({ level: '', state: 'open' })

const resolveVisible = ref(false)
const current = ref({})
const note = ref('')

function levelType(level) {
  return { critical: 'danger', warning: 'warning', notice: 'info', info: 'success' }[level] || 'info'
}

async function load() {
  loading.value = true
  try {
    const data = await api.alerts({
      level: filters.level,
      state: filters.state,
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

function openDevice(id) {
  router.push({ name: 'device-detail', params: { id } })
}

function openResolve(row) {
  current.value = row
  note.value = ''
  resolveVisible.value = true
}

async function submitResolve() {
  try {
    await api.resolveAlert(current.value.id, note.value)
    resolveVisible.value = false
    ElMessage.success('已标记处理')
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
