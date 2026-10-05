<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api } from '../api'
import { currentHallId, halls, loadHalls } from '../halls'

const viols = ref<any[]>([])
const unplaced = ref<any[]>([])
const meta = ref<any>({})

async function load() {
  const res = await api(`/seating/violations?hall_id=${currentHallId.value}`)
  viols.value = res.violations; unplaced.value = res.unplaced
  meta.value = await api(`/seating/latest?hall_id=${currentHallId.value}`)
}
onMounted(async () => { await loadHalls(); await load() })
watch(currentHallId, load)
</script>
<template>
  <h1>违规</h1>
  <p class="sub">间距不足或同试卷四邻相邻 · 合排后按当前考室对账切片展示</p>

  <label style="font-family:'Segoe UI',sans-serif;font-size:0.86rem">考室
    <select v-model.number="currentHallId" style="margin-left:0.3rem;padding:0.3rem">
      <option v-for="h in halls" :key="h.id" :value="h.id">{{ h.code }} {{ h.name }}</option>
    </select>
  </label>
  <span v-if="meta.merged" class="badge badge-warn" style="margin-left:0.7rem">
    合排批次 {{ meta.merge_key }} · 本室切片（考室{{ meta.hall.id }}）
  </span>

  <div class="card" style="margin-top:0.85rem">
    <table>
      <thead><tr><th>类型</th><th>考生A</th><th>考生B</th><th>说明</th></tr></thead>
      <tbody>
        <tr v-for="(v,i) in viols" :key="i">
          <td>{{ v.kind }}</td><td>{{ v.a_id }}</td><td>{{ v.b_id }}</td><td>{{ v.detail }}</td>
        </tr>
      </tbody>
    </table>
    <p v-if="!viols.length" class="muted">无违规</p>
  </div>
  <div class="card" v-if="unplaced.length">
    <h3>未排上</h3>
    <div v-for="u in unplaced" :key="u.id">{{ u.name }}（{{ u.ticket_no }}）</div>
  </div>
</template>
