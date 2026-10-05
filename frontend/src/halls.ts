import { ref } from 'vue'
import { api } from './api'

export interface Hall {
  id: number
  code: string
  name: string
  rows: number
  cols: number
  min_manhattan: number
  merged_into: number | null
}

// 全局共享当前选中的考室，跨页（排座图/统计/违规）保持一致
export const currentHallId = ref<number>(1)
export const halls = ref<Hall[]>([])
export const hallsLoaded = ref(false)

export async function loadHalls() {
  if (!halls.value.length) currentHallId.value = 1
  halls.value = await api('/halls')
  hallsLoaded.value = true
  if (!halls.value.some(h => h.id === currentHallId.value) && halls.value.length) {
    currentHallId.value = halls.value[0].id
  }
  return halls.value
}

export function hallName(id: number | undefined): string {
  if (id == null) return ''
  return halls.value.find(h => h.id === id)?.name ?? `考室 ${id}`
}
