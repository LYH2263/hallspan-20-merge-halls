<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

interface Hall { id: number; code: string; name: string; rows: number; cols: number; min_manhattan: number; merged_into: number | null }

const rows = ref<Hall[]>([])
const hallA = ref<number | null>(null)
const hallB = ref<number | null>(null)
const busy = ref(false)
const error = ref('')
const okMsg = ref('')

async function load() {
  rows.value = await api('/halls')
  if (!hallA.value && rows.value.length) hallA.value = rows.value[0].id
  if (!hallB.value && rows.value.length > 1) hallB.value = rows.value[1].id
}
onMounted(load)

const standalone = computed(() => rows.value.filter(h => h.merged_into == null))
const mergedGroups = computed(() => {
  const groups = new Map<number, Hall[]>()
  for (const h of rows.value) {
    if (h.merged_into == null) continue
    if (!groups.has(h.merged_into)) groups.set(h.merged_into, [])
    groups.get(h.merged_into)!.push(h)
  }
  return [...groups.entries()].map(([master, hs]) => ({ master, halls: hs }))
})

async function applyMerge() {
  error.value = ''; okMsg.value = ''
  if (hallA.value == null || hallB.value == null) { error.value = '请选择两间考室'; return }
  if (hallA.value === hallB.value) { error.value = '必须选择两间不同的考室'; return }
  busy.value = true
  try {
    const res = await api('/seating/merge', {
      method: 'POST',
      body: JSON.stringify({ hall_a_id: hallA.value, hall_b_id: hallB.value }),
    })
    const per = res.room_slices?.map((s: any) => `考室${s.hall_id} ${s.stats.seated}人`).join(' + ') ?? ''
    okMsg.value = `合排成功（批次 ${res.merge_key}）：${per} = 合排已座 ${res.stats.seated} 人，两室均已留下对账方案`
    await load()
  } catch (e: any) {
    error.value = '合排失败，双室方案/统计/未排已全部回滚：' + (e.message || e)
  } finally {
    busy.value = false
  }
}
</script>
<template>
  <h1>考室</h1>
  <p class="sub">考室网格、最小曼哈顿间距与两考室一次合排（成功双室对账，失败双室回滚）</p>

  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>行</th><th>列</th><th>最小间距</th><th>状态</th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.code }}</td><td>{{ r.name }}</td>
          <td>{{ r.rows }}</td><td>{{ r.cols }}</td><td>{{ r.min_manhattan }}</td>
          <td>
            <span v-if="r.merged_into == null" class="badge badge-ok">独立</span>
            <span v-else class="badge badge-warn">已合排 → 主室 {{ r.merged_into }}</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>

  <div class="card">
    <h3 style="margin-top:0">申请两考室合排</h3>
    <div style="display:flex;gap:0.6rem;align-items:center;flex-wrap:wrap;font-family:'Segoe UI',sans-serif;font-size:0.86rem">
      <label>考室一
        <select v-model.number="hallA" style="margin-left:0.3rem;padding:0.3rem">
          <option v-for="h in standalone" :key="h.id" :value="h.id">{{ h.code }} {{ h.name }}</option>
        </select>
      </label>
      <label>考室二
        <select v-model.number="hallB" style="margin-left:0.3rem;padding:0.3rem">
          <option v-for="h in standalone" :key="h.id" :value="h.id">{{ h.code }} {{ h.name }}</option>
        </select>
      </label>
      <button class="btn" :disabled="busy" @click="applyMerge">{{ busy ? '合排中…' : '申请合排' }}</button>
    </div>
    <p v-if="error" class="badge badge-bad" style="margin-top:0.7rem;padding:0.45rem 0.6rem">{{ error }}</p>
    <p v-if="okMsg" class="badge badge-ok" style="margin-top:0.7rem;padding:0.45rem 0.6rem">{{ okMsg }}</p>
    <p class="muted" style="font-size:0.78rem;margin-bottom:0">
      成功：两室都留下对账方案与统一指针，考生不丢，分室人数相加等于合排已座；任一步失败：两室方案、统计、未排全部退回，不留合排指针；未参与的第三室不做任何改动。
    </p>
  </div>

  <div class="card" v-if="mergedGroups.length">
    <h3 style="margin-top:0">当前合排组</h3>
    <div v-for="g in mergedGroups" :key="g.master">
      <span class="badge badge-warn">主室 {{ g.master }}</span>
      {{ g.halls.map(h => h.code + ' ' + h.name).join(' ⇄ ') }}
    </div>
  </div>
</template>
