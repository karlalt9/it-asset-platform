import { createRouter, createWebHistory } from 'vue-router'

import Alerts from './views/Alerts.vue'
import DeviceDetail from './views/DeviceDetail.vue'
import Devices from './views/Devices.vue'
import Overview from './views/Overview.vue'

const routes = [
  { path: '/', name: 'overview', component: Overview, meta: { title: '总览' } },
  { path: '/devices', name: 'devices', component: Devices, meta: { title: '设备资产' } },
  {
    path: '/devices/:id',
    name: 'device-detail',
    component: DeviceDetail,
    props: true,
    meta: { title: '设备详情' },
  },
  { path: '/alerts', name: 'alerts', component: Alerts, meta: { title: '告警中心' } },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
