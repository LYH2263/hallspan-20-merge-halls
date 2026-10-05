<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { currentHallId, halls, loadHalls } from '../halls'

const data = ref<any>(null)
const candidates = ref<any[]>([])
const violKeys = ref<Set<string>>(new Set())
const err = ref('')

async function run() {
  err.value = ''
  try {
    data.value = await api(`/seating/run?hall_id=${currentHallId.value}`, { method: 'POST' })
  } catch (e: any) {
    err.value = e?.message || String(e)
    data.value = await api(`/seating/latest?hall_id=${currentHallId.value}`)
  }
  await loadView()
}

async function loadView() {
  data.value = await api(`/seating/latest?hall_id=${currentHallId.value}`)
  try {
    const v = await api(`/seating/violations?hall_id=${currentHallId.value}`)
    const keys = new Set<string>()
    for (const x of v.violations || []) {
      if (x.a_id != null) keys.add(String(x.a_id))
      if (x.b_id != null) keys.add(String(x.b_id))
    }
    violKeys.value = keys
  } catch { violKeys.value = new Set() }
}

onMounted(async () => {
  await loadHalls()
  candidates.value = await api('/candidates')
  await loadView()
})

watch(currentHallId, loadView)

const roomCandidates = computed(() => candidates.value.filter(c => c.hall_id === currentHallId.value))

const gridStyle = computed(() => data.value ? ({ gridTemplateColumns: `repeat(${data.value.cols}, 72px)` }) : {})
const cells = computed(() => {
  if (!data.value) return []
  const map = new Map<string, any>()
  for (const a of data.value.assignments || []) map.set(a.row + ',' + a.col, a)
  const out: any[] = []
  for (let r = 0; r < data.value.rows; r++) {
    for (let c = 0; c < data.value.cols; c++) {
      out.push(map.get(r + ',' + c) || { empty: true, row: r, col: c })
    }
  }
  return out
})
function isViol(cell: any) {
  if (cell.empty) return false
  const id = cell.candidate_id ?? cell.id
  return id != null && violKeys.value.has(String(id))
}
function paperClass(pid: number) {
  return pid % 2 === 0 ? 'b' : 'a'
}
</script>
<template>
  <h1>考场课桌网格</h1>
  <p class="sub">课桌网格为主视图 · 左侧考生名册夹板 · 违规课桌高亮 · 合排后跟随统一指针</p>

  <div style="display:flex;gap:0.6rem;align-items:center;margin-bottom:0.7rem;flex-wrap:wrap">
    <label style="font-family:'Segoe UI',sans-serif;font-size:0.86rem">考室
      <select v-model.number="currentHallId" style="margin-left:0.3rem;padding:0.3rem">
        <option v-for="h in halls" :key="h.id" :value="h.id">
          {{ h.code }} {{ h.name }}{{ h.merged_into != null ? '（已合排）' : '' }}
        </option>
      </select>
    </label>
    <button class="btn" @click="run" :disabled="data?.merged">重新排座</button>
  </div>

  <div v-if="data?.merged" class="card" style="border-color:#c08a2a">
    <strong>两考室合排方案</strong>
    <span class="badge badge-warn" style="margin-left:0.5rem">统一指针 → 主室 {{ data.master_id }}</span>
    <div style="margin-top:0.5rem;font-family:'Segoe UI',sans-serif;font-size:0.85rem">
      批次 {{ data.merge_key }}
      <div v-for="r in data.room_stats" :key="r.hall_id">
        考室{{ r.hall_id }} {{ r.name }}：已座 <strong>{{ r.seated }}</strong> 人
      </div>
      <div style="margin-top:0.3rem">
        分室人数相加 <strong>{{ data.room_stats.reduce((n: number, r: any) => n + r.seated, 0) }}</strong>
        ＝ 合排已座 <strong>{{ data.merged_stats.seated }}</strong> 人，未排 {{ data.merged_stats.unplaced }} 人
      </div>
      <div class="muted" style="font-size:0.78rem">当前显示本室（考室{{ data.hall.id }}）对账切片，另一考室页面见同批次方案</div>
    </div>
  </div>

  <p v-if="err" class="badge badge-bad" style="padding:0.45rem 0.6rem">{{ err }}</p>

  <div class="hs-classroom" style="margin-top:0.85rem">
    <aside class="hs-clipboard">
      <h2>考生名册（本室 {{ roomCandidates.length }} 人）</h2>
      <div v-for="c in roomCandidates" :key="c.id" class="hs-roster-row">
        <div>
          <div>{{ c.name }}</div>
          <div class="hs-ticket">{{ c.ticket_no }}</div>
        </div>
        <div>卷{{ c.paper_id }}</div>
      </div>
    </aside>
    <div class="hs-desk-stage" v-if="data">
      <div class="hs-grid-board" :style="gridStyle">
        <div
          v-for="(cell,i) in cells" :key="i"
          class="hs-desk"
          :class="{ empty: cell.empty, 'hs-viol': isViol(cell) }"
        >
          <template v-if="!cell.empty">
            <span class="hs-paper-tag" :class="paperClass(cell.paper_id)">卷{{ cell.paper_id }}</span>
            <div>{{ cell.name }}</div>
          </template>
          <template v-else>·</template>
        </div>
      </div>
    </div>
  </div>
</template>
