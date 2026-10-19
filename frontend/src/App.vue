<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import type { Paper, Stats, FilterType, StatusFilter, AppSettings, DirectionSummary } from './types/paper'
import {
  fetchPapers,
  fetchStats,
  fetchPapersStream,
  fetchPendingPaperIds,
  fetchSettings,
  fetchPaper,
  fetchDirections,
} from './services/api'
import { useProcessingStore } from './stores/processing'
import { getLogger } from './utils/logger'
import { analysisSetupProblem } from './utils/settings'
import AppSidebar from './components/layout/AppSidebar.vue'
import DirectionTabs from './components/layout/DirectionTabs.vue'
import PaperCard from './components/paper/PaperCard.vue'
import ArxivImportModal from './components/ArxivImportModal.vue'
import DemoBanner from './demo/DemoBanner.vue'

const isDemo = import.meta.env.VITE_DEMO === 'true'

const logger = getLogger('App')
const ACTIVE_DIRECTION_KEY = 'paperinsight.activeDirection'

const processing = useProcessingStore()

const papers = ref<Paper[]>([])
const stats = ref<Stats | null>(null)
const settings = ref<AppSettings | null>(null)
const directions = ref<DirectionSummary[]>([])
const activeDirectionId = ref<number | null>(readStoredDirection())
const loading = ref(false)
const fetching = ref(false)
const error = ref<string | null>(null)
const showImportModal = ref(false)

const sidebarRef = ref<InstanceType<typeof AppSidebar> | null>(null)

const activeDirection = computed(() =>
  directions.value.find(d => d.id === activeDirectionId.value) ?? null
)

// Anything being analyzed: our queue, or the backend scheduler (any direction)
const processingActive = computed(() =>
  processing.state.running.length > 0
  || processing.state.queue.length > 0
  || directions.value.some(d => d.processing > 0)
)
const busyDirectionIds = computed(() => processing.activeDirections())

// First-run hint: analysis needs a reasoning model with an API key
const setupProblem = computed(() => analysisSetupProblem(settings.value))

const relevanceFilter = ref<FilterType>('all')
const statusFilter = ref<StatusFilter>('all')

const focusKeywords = computed(() => activeDirection.value?.focus_keywords ?? [])

const filteredPapers = computed(() => {
  let result = papers.value

  // Filter by relevance
  if (relevanceFilter.value === 'high') {
    result = result.filter(p => p.relevance_score !== null && p.relevance_score >= 9)
  }
  else if (relevanceFilter.value === 'low') {
    result = result.filter(p => p.relevance_score !== null && p.relevance_score >= 5 && p.relevance_score < 9)
  }

  // Filter by status
  if (statusFilter.value === 'processed') {
    result = result.filter(p => p.is_processed)
  }
  else if (statusFilter.value === 'pending') {
    result = result.filter(p => !p.is_processed)
  }

  return result
})

function readStoredDirection(): number | null {
  try {
    const value = Number(localStorage.getItem(ACTIVE_DIRECTION_KEY))
    return Number.isFinite(value) && value > 0 ? value : null
  } catch {
    return null
  }
}

watch(activeDirectionId, (id) => {
  try {
    if (id != null) localStorage.setItem(ACTIVE_DIRECTION_KEY, String(id))
  } catch {
    // storage unavailable: just don't remember the tab
  }
})

async function loadDirections() {
  directions.value = await fetchDirections()
  if (!directions.value.some(d => d.id === activeDirectionId.value)) {
    activeDirectionId.value = directions.value[0]?.id ?? null
  }
}

async function loadData() {
  loading.value = papers.value.length === 0
  error.value = null

  try {
    const [settingsData] = await Promise.all([fetchSettings(), loadDirections()])
    settings.value = settingsData
    const directionId = activeDirectionId.value ?? undefined
    const [papersData, statsData] = await Promise.all([
      fetchPapers({ limit: 100, direction_id: directionId }),
      fetchStats(directionId),
    ])
    papers.value = papersData
    stats.value = statsData
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load data'
    logger.error('Failed to load data', e)
  } finally {
    loading.value = false
  }
}

function selectDirection(id: number) {
  if (id === activeDirectionId.value) return
  activeDirectionId.value = id
  papers.value = []
  loadData()
}

function addDirection() {
  sidebarRef.value?.openSettings('research', { newDirection: true })
}

async function handleFetch() {
  if (fetching.value) return

  fetching.value = true
  error.value = null

  fetchPapersStream({
    onDone: async (event) => {
      fetching.value = false
      await loadData()
      // Analyze what was just fetched
      if (event.saved > 0) handleBatchProcess()
    },
    onError: (err) => {
      error.value = err.message || 'Failed to fetch papers'
      fetching.value = false
    },
  }, activeDirectionId.value)
}

async function handleBatchProcess() {
  error.value = null
  try {
    // Queue this direction's pending papers; the global queue shares its slots with
    // the other directions and starts MinerU on all of them right away
    const pendingIds = await fetchPendingPaperIds(activeDirectionId.value)
    processing.enqueue(pendingIds, activeDirectionId.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to start batch processing'
  }
}

async function handleStopAll() {
  await processing.stopAll()
  await loadData()
}

function handleSettingsSaved() {
  loadData() // Reload everything: directions may have been added, renamed or removed
}

function handlePaperDeleted(paperId: number) {
  papers.value = papers.value.filter(p => p.id !== paperId)
  if (stats.value) {
    stats.value.total_papers = Math.max(0, stats.value.total_papers - 1)
  }
  loadDirections()
}

// Update a single paper in place (keeps the list order) plus the counters
async function updatePaperById(paperId: number) {
  try {
    const updatedPaper = await fetchPaper(paperId)
    const index = papers.value.findIndex(p => p.id === paperId)
    if (index !== -1) papers.value[index] = updatedPaper
    const [newStats] = await Promise.all([fetchStats(activeDirectionId.value), loadDirections()])
    stats.value = newStats
  } catch (e) {
    logger.error('Failed to update paper', e)
  }
}

async function handlePaperImported(paperId: number, isNew: boolean) {
  await loadData()
  if (isNew) processing.analyzeNow(paperId, activeDirectionId.value)
}

// Runs finish independently of the cards (other tabs included): refresh what's shown
const stopListening = processing.onPaperChanged((paperId) => {
  if (papers.value.some(p => p.id === paperId)) updatePaperById(paperId)
  else loadDirections()
})

onMounted(loadData)
onUnmounted(stopListening)
</script>

<template>
  <div class="flex min-h-screen bg-[var(--color-paper-50)]">
    <!-- Sidebar -->
    <AppSidebar
      ref="sidebarRef"
      :stats="stats"
      :settings="settings"
      :relevance-filter="relevanceFilter"
      :status-filter="statusFilter"
      :loading="fetching"
      :batch-processing="processingActive"
      :processing-active="processingActive"
      :stopping="processing.state.stopping"
      :active-direction-id="activeDirectionId"
      @update:relevance-filter="relevanceFilter = $event"
      @update:status-filter="statusFilter = $event"
      @fetch="handleFetch"
      @batch-process="handleBatchProcess"
      @stop-processing="handleStopAll"
      @import="showImportModal = true"
      @settings-saved="handleSettingsSaved"
    />

    <!-- Main Content -->
    <main class="flex-1 min-w-0">
      <!-- Header -->
      <header class="sticky top-0 z-10 bg-[var(--color-paper-50)]/80 backdrop-blur-sm border-b border-[var(--color-paper-200)] px-8 py-4">
        <!-- One tab per research direction (mirrors Settings → 研究方向) -->
        <DirectionTabs
          v-if="directions.length"
          class="mb-3"
          :directions="directions"
          :active-id="activeDirectionId"
          :busy-ids="busyDirectionIds"
          @select="selectDirection"
          @add="addDirection"
        />
        <!-- One line: paper count · research focus · search -->
        <div class="flex items-center gap-4">
          <div class="flex-1 min-w-0 flex items-center gap-3">
            <span class="flex-shrink-0 text-sm text-[var(--color-ink-400)] whitespace-nowrap">
              {{ filteredPapers.length }} papers<span v-if="relevanceFilter !== 'all' || statusFilter !== 'all'"> (filtered)</span>
            </span>
            <span class="flex-shrink-0 h-4 w-px bg-[var(--color-paper-300)]"></span>
            <span class="flex-shrink-0 text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] whitespace-nowrap">
              Research Focus
            </span>
            <div
              v-if="focusKeywords.length > 0"
              class="min-w-0 flex items-center gap-2 overflow-hidden [mask-image:linear-gradient(to_right,black_88%,transparent)]"
              :title="focusKeywords.join(' · ')"
            >
              <span
                v-for="keyword in focusKeywords"
                :key="keyword"
                class="flex-shrink-0 px-2.5 py-1 rounded-md bg-[var(--color-paper-100)] border border-[var(--color-paper-200)] text-xs text-[var(--color-ink-700)] font-mono shadow-sm"
              >
                {{ keyword }}
              </span>
            </div>
            <span v-else class="min-w-0 truncate text-xs text-[var(--color-ink-400)] italic">
              No focus set. Default query used.
            </span>
          </div>

          <!-- Search (placeholder) -->
          <div class="relative flex-shrink-0">
            <svg
              class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--color-ink-400)]"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Search papers..."
              class="w-64 pl-10 pr-4 py-2 bg-[var(--color-paper-100)] border border-[var(--color-paper-200)] rounded-lg text-sm text-[var(--color-ink-700)] placeholder-[var(--color-ink-400)] focus:outline-none focus:ring-2 focus:ring-[var(--color-ink-200)] focus:border-transparent transition-all"
            />
          </div>
        </div>
      </header>

      <!-- Content Area -->
      <div class="p-8">
        <!-- First-run setup banner -->
        <div
          v-if="setupProblem && !loading"
          class="mb-6 flex items-center justify-between gap-4 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4"
        >
          <div v-if="setupProblem.kind === 'key'">
            <p class="text-sm font-semibold text-amber-900">填写 {{ setupProblem.provider.name }} API Key 以开始分析论文</p>
            <p class="text-xs text-amber-800 mt-0.5">
              默认使用 DeepSeek-V4.1-Flash（deepseek-flash）完成图像识别与推理分析；PDF 解析使用 MinerU（云端 Token 或本地安装）。
            </p>
          </div>
          <div v-else>
            <p class="text-sm font-semibold text-amber-900">配置模型以开始分析论文</p>
            <p class="text-xs text-amber-800 mt-0.5">
              添加一个兼容 OpenAI 接口的模型服务，然后在「解析流程」中选择推理模型、视觉模型与 MinerU 解析方式。
            </p>
          </div>
          <button
            class="flex-shrink-0 px-3 py-1.5 text-sm font-medium text-white bg-[var(--color-ink-900)] rounded-lg hover:bg-[var(--color-ink-700)] transition-colors"
            @click="sidebarRef?.openSettings(setupProblem.kind === 'key' || !settings?.providers.length ? 'providers' : 'pipeline')"
          >
            打开设置
          </button>
        </div>

        <!-- Loading State -->
        <div v-if="loading" class="flex items-center justify-center py-20">
          <div class="flex items-center gap-3 text-[var(--color-ink-400)]">
            <svg class="w-6 h-6 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span>Loading papers...</span>
          </div>
        </div>

        <!-- Error State -->
        <div v-else-if="error" class="flex flex-col items-center justify-center py-20">
          <div class="text-[var(--color-relevance-high)] mb-4">
            <svg class="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
          </div>
          <p class="text-[var(--color-ink-700)] mb-4">{{ error }}</p>
          <button
            @click="loadData"
            class="px-4 py-2 bg-[var(--color-ink-900)] text-white text-sm font-medium rounded-lg hover:bg-[var(--color-ink-700)] transition-colors"
          >
            Try Again
          </button>
        </div>

        <!-- Empty State -->
        <div v-else-if="filteredPapers.length === 0" class="flex flex-col items-center justify-center py-20">
          <div class="text-[var(--color-ink-200)] mb-4">
            <svg class="w-16 h-16" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
          </div>
          <p class="text-[var(--color-ink-700)] font-medium mb-2">No papers found</p>
          <p class="text-sm text-[var(--color-ink-400)] mb-4">
            {{ papers.length > 0 ? 'Try adjusting your filters' : 'Click "Fetch New Papers" to get started' }}
          </p>
        </div>

        <!-- Papers Grid -->
        <div v-else class="space-y-4">
          <PaperCard
            v-for="paper in filteredPapers"
            :key="paper.id"
            :paper="paper"
            class="animate-slide-up"
            :style="{ animationDelay: `${filteredPapers.indexOf(paper) * 50}ms` }"
            @refresh="updatePaperById"
            @delete="handlePaperDeleted"
          />
        </div>
      </div>
    </main>

    <DemoBanner v-if="isDemo" />

    <!-- Import Modal -->
    <ArxivImportModal
      :show="showImportModal"
      :direction-id="activeDirectionId"
      :direction-name="activeDirection?.name"
      @close="showImportModal = false"
      @imported="handlePaperImported"
    />
  </div>
</template>
