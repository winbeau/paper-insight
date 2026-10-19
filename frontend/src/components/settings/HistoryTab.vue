<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import type { DirectionSummary, HistoryItem, StorageUsage } from '../../types/paper'
import { clearHistory, deleteHistory, fetchDirections, fetchHistory, pruneCache } from '../../services/api'
import { useProcessingStore } from '../../stores/processing'

const PAGE_SIZE = 50

const STATUS_LABELS: Record<string, { label: string; cls: string }> = {
  processed: { label: '已分析', cls: 'bg-emerald-50 text-emerald-700' },
  skipped: { label: '低相关', cls: 'bg-gray-100 text-gray-500' },
  failed: { label: '失败', cls: 'bg-red-50 text-red-600' },
  pending: { label: '待分析', cls: 'bg-amber-50 text-amber-700' },
  processing: { label: '分析中', cls: 'bg-amber-100 text-amber-800' },
}

const processing = useProcessingStore()

const directions = ref<DirectionSummary[]>([])
const filter = reactive<{ direction_id: number | null; status: string; q: string }>({
  direction_id: null, status: '', q: '',
})
const items = ref<HistoryItem[]>([])
const total = ref(0)
const storage = ref<StorageUsage | null>(null)
const loading = ref(false)
const busy = ref(false)
const selected = ref<Set<number>>(new Set())
const deleteFiles = ref(true)
const confirmingClear = ref(false)
const confirmRowId = ref<number | null>(null)
const notice = ref('')

const allOnPageSelected = computed(
  () => items.value.length > 0 && items.value.every(item => selected.value.has(item.id)),
)
const filterActive = computed(() => filter.direction_id != null || !!filter.status || !!filter.q.trim())

function formatBytes(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

async function load(reset = true) {
  loading.value = true
  try {
    const page = await fetchHistory(filter, reset ? 0 : items.value.length, PAGE_SIZE)
    items.value = reset ? page.items : [...items.value, ...page.items]
    total.value = page.total
    storage.value = page.storage
    if (reset) selected.value = new Set()
  } finally {
    loading.value = false
  }
}

function toggle(id: number) {
  const next = new Set(selected.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selected.value = next
}

function toggleAll() {
  selected.value = allOnPageSelected.value ? new Set() : new Set(items.value.map(item => item.id))
}

function report(result: { deleted: number; skipped_active: number; freed_bytes: number }) {
  const parts = [`已删除 ${result.deleted} 条`]
  if (result.freed_bytes) parts.push(`释放 ${formatBytes(result.freed_bytes)}`)
  if (result.skipped_active) parts.push(`${result.skipped_active} 篇正在分析，已跳过`)
  notice.value = parts.join('，')
}

async function run(action: () => Promise<{ deleted: number; skipped_active: number; freed_bytes: number }>, ids: number[]) {
  busy.value = true
  try {
    const result = await action()
    processing.forget(ids)
    report(result)
    await load()
  } finally {
    busy.value = false
    confirmingClear.value = false
    confirmRowId.value = null
  }
}

function deleteOne(id: number) {
  run(() => deleteHistory([id], deleteFiles.value), [id])
}

function deleteSelected() {
  const ids = [...selected.value]
  if (ids.length) run(() => deleteHistory(ids, deleteFiles.value), ids)
}

function clearFiltered() {
  run(() => clearHistory(filter, deleteFiles.value), items.value.map(item => item.id))
}

async function prune() {
  busy.value = true
  try {
    const result = await pruneCache()
    storage.value = result.storage
    notice.value = result.removed ? `清理了 ${result.removed} 项无用缓存，释放 ${formatBytes(result.freed_bytes)}` : '没有无用缓存'
  } finally {
    busy.value = false
  }
}

let searchTimer: ReturnType<typeof setTimeout> | null = null
watch(() => [filter.direction_id, filter.status], () => { confirmingClear.value = false; load() })
watch(() => filter.q, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { confirmingClear.value = false; load() }, 300)
})

onMounted(async () => {
  directions.value = await fetchDirections().catch(() => [])
  await load()
})
</script>

<template>
  <div class="space-y-4">
    <!-- Local cache -->
    <div class="flex items-center justify-between gap-4 rounded-lg border border-gray-200 bg-gray-50/60 px-4 py-3">
      <div class="text-xs text-gray-600">
        <span class="font-medium text-gray-900">本地缓存</span>
        <span v-if="storage" class="ml-2">
          {{ formatBytes(storage.total) }}
          <span class="text-gray-400">（PDF {{ formatBytes(storage.pdfs) }} · 解析结果 {{ formatBytes(storage.parsed) }} · 缩略图 {{ formatBytes(storage.thumbnails) }}）</span>
        </span>
      </div>
      <button
        :disabled="busy"
        class="flex-shrink-0 px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50"
        title="删除已不属于任何研究方向的论文缓存文件"
        @click="prune"
      >
        清理无用缓存
      </button>
    </div>

    <!-- Filters -->
    <div class="flex items-center gap-2">
      <select
        v-model="filter.direction_id"
        class="px-2 py-1.5 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
      >
        <option :value="null">全部方向</option>
        <option v-for="d in directions" :key="d.id" :value="d.id">{{ d.name }}</option>
      </select>
      <select
        v-model="filter.status"
        class="px-2 py-1.5 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
      >
        <option value="">全部状态</option>
        <option v-for="(meta, key) in STATUS_LABELS" :key="key" :value="key">{{ meta.label }}</option>
      </select>
      <input
        v-model="filter.q"
        class="flex-1 min-w-0 px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
        placeholder="搜索标题或 arXiv ID"
      />
    </div>

    <!-- Bulk actions -->
    <div class="flex items-center gap-3 text-xs">
      <label class="flex items-center gap-1.5 text-gray-600">
        <input type="checkbox" :checked="allOnPageSelected" :disabled="!items.length" @change="toggleAll" />
        全选本页
      </label>
      <button
        :disabled="busy || selected.size === 0"
        class="px-2.5 py-1 rounded-md border border-red-200 text-red-600 hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed"
        @click="deleteSelected"
      >
        删除所选{{ selected.size ? `（${selected.size}）` : '' }}
      </button>
      <template v-if="confirmingClear">
        <span class="text-gray-500">确认删除{{ filterActive ? '筛选出的' : '全部' }} {{ total }} 条记录？</span>
        <button class="px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50" @click="confirmingClear = false">取消</button>
        <button :disabled="busy" class="px-2.5 py-1 rounded-md text-white bg-red-600 hover:bg-red-700 disabled:opacity-50" @click="clearFiltered">确认清空</button>
      </template>
      <button
        v-else
        :disabled="busy || total === 0"
        class="px-2.5 py-1 rounded-md text-gray-500 hover:text-red-600 hover:bg-red-50 disabled:opacity-40 disabled:cursor-not-allowed"
        @click="confirmingClear = true"
      >
        {{ filterActive ? `清空筛选结果（${total}）` : `清空全部历史（${total}）` }}
      </button>
      <label class="ml-auto flex items-center gap-1.5 text-gray-500" title="PDF、MinerU 解析结果与缩略图；仍被其他方向使用的论文会保留">
        <input v-model="deleteFiles" type="checkbox" />
        同时删除缓存文件
      </label>
    </div>

    <p v-if="notice" class="text-xs text-emerald-700">{{ notice }}</p>

    <!-- Entries -->
    <div class="border border-gray-200 rounded-lg divide-y divide-gray-100">
      <div v-if="!items.length" class="px-4 py-10 text-center text-sm text-gray-400">
        {{ loading ? '加载中…' : '没有记录' }}
      </div>
      <div
        v-for="item in items"
        :key="item.id"
        class="group flex items-center gap-3 px-3 py-2 hover:bg-gray-50/70"
      >
        <input type="checkbox" :checked="selected.has(item.id)" @change="toggle(item.id)" />
        <div class="flex-1 min-w-0">
          <p class="text-sm text-gray-900 truncate" :title="item.title">{{ item.title }}</p>
          <p class="mt-0.5 flex items-center gap-2 text-[11px] text-gray-400">
            <span class="font-mono">{{ item.arxiv_id }}</span>
            <span>·</span>
            <span class="truncate max-w-[140px]">{{ item.direction_name }}</span>
            <span>·</span>
            <span>添加于 {{ formatDate(item.created_at) }}</span>
            <span v-if="item.relevance_score != null">· 相关性 {{ item.relevance_score }}</span>
          </p>
        </div>
        <span
          class="flex-shrink-0 px-1.5 py-0.5 rounded text-[10px] font-medium"
          :class="STATUS_LABELS[item.processing_status]?.cls ?? 'bg-gray-100 text-gray-500'"
        >
          {{ STATUS_LABELS[item.processing_status]?.label ?? item.processing_status }}
        </span>
        <button
          v-if="confirmRowId === item.id"
          :disabled="busy"
          class="flex-shrink-0 px-2 py-0.5 rounded text-[11px] text-white bg-red-600 hover:bg-red-700"
          @click="deleteOne(item.id)"
        >
          确认删除
        </button>
        <button
          v-else
          class="flex-shrink-0 p-1 rounded text-gray-300 hover:text-red-600 hover:bg-red-50 opacity-0 group-hover:opacity-100 transition-opacity"
          title="删除此条"
          @click="confirmRowId = item.id"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
          </svg>
        </button>
      </div>
    </div>

    <div class="flex items-center justify-between text-xs text-gray-400">
      <span>显示 {{ items.length }} / {{ total }} 条 · 删除立即生效（与 Save Changes 无关），正在分析的论文会被跳过</span>
      <button
        v-if="items.length < total"
        :disabled="loading"
        class="px-2.5 py-1 rounded-md border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
        @click="load(false)"
      >
        加载更多
      </button>
    </div>
  </div>
</template>
