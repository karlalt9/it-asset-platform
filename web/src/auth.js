import { ref } from 'vue'

const STORAGE_KEY = 'iap_read_token'

/** 看板读取令牌，保存在浏览器本地，不会随请求发给除本服务以外的任何地方。 */
export const readToken = ref(localStorage.getItem(STORAGE_KEY) || '')

/** 服务端返回 401 时置为 true，界面据此弹出授权输入框。 */
export const needAuth = ref(false)

export function setReadToken(value) {
  readToken.value = String(value || '').trim()
  if (readToken.value) {
    localStorage.setItem(STORAGE_KEY, readToken.value)
  }
  else {
    localStorage.removeItem(STORAGE_KEY)
  }
  needAuth.value = false
}

export function clearReadToken() {
  readToken.value = ''
  localStorage.removeItem(STORAGE_KEY)
  needAuth.value = true
}
