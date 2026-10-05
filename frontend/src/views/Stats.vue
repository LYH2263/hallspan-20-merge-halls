<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { currentHallId, halls, loadHalls } from '../halls'

const s = ref<any>({})
async function load() { s.value = await api(`/seating/stats?hall_id=${currentHallId.value}`) }
onMounted(async () => { await loadHalls(); await load() })
watch(currentHallId, load)
</script>
<template>
  <h1>统计</h1>
  <p class="sub">排座占用与违规汇总 · 合排后分室人数相加须等于合排已座</p>

  <label style="font-family:'Segoe UI',sans-serif;font-size:0.86rem">考室
    <select v-model.number="currentHallId" style="margin-left:0.3rem;padding:0.3rem">
      <option v-for="h in halls" :key="h.id" :value="h.id">{{ h.code }} {{ h.name }}</option>
    </select>
  </label>

  <div v-if="s.merged" class="card" style="margin-top:0.85rem;border-color:#c08a2a">
    <strong>两考室合排统计</strong>
    <span class="badge badge-warn" style="margin-left:0.5rem">批次 {{ s.merge_key }}</span>
    <table style="margin-top:0.6rem">
      <thead><tr><th>考室</th><th>已座</th><th>未排</th><th>违规</th><th>容量</th></tr></thead>
      <tbody>
        <tr v-for="r in s.room_stats" :key="r.hall_id">
          <td>考室{{ r.hall_id }} {{ r.name }}</td>
          <td>{{ r.seated }}</td><td>{{ r.unplaced }}</td><td>{{ r.violations }}</td><td>{{ r.capacity }}</td>
        </tr>
        <tr style="font-weight:800;border-top:2px solid #b0a890">
          <td>合排合计（分室相加）</td>
          <td>{{ s.room_stats.reduce((n: number, r: any) => n + r.seated, 0) }}</td>
          <td>{{ s.room_stats.reduce((n: number, r: any) => n + r.unplaced, 0) }}</td>
          <td>{{ s.room_stats.reduce((n: number, r: any) => n + r.violations, 0) }}</td>
          <td>{{ s.room_stats.reduce((n: number, r: any) => n + r.capacity, 0) }}</td>
        </tr>
      </tbody>
    </table>
    <p style="margin-bottom:0" class="badge badge-ok">
      对账一致：分室人数相加 {{ s.room_stats.reduce((n: number, r: any) => n + r.seated, 0) }}
      ＝ 合排已座 {{ s.merged_seated }}
    </p>
  </div>

  <div class="card" style="margin-top:0.85rem;display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1rem">
    <div><div class="muted">{{ s.merged ? '本室已排座' : '已排座' }}</div><div class="stat">{{ s.seated }}</div></div>
    <div><div class="muted">未排上</div><div class="stat">{{ s.unplaced }}</div></div>
    <div><div class="muted">违规数</div><div class="stat">{{ s.violations }}</div></div>
    <div><div class="muted">座位容量</div><div class="stat">{{ s.capacity }}</div></div>
  </div>
</template>
