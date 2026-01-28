<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import type { Paper, Stats, FilterType, StatusFilter, AppSettings } from './types/paper'
import { fetchPapers, fetchStats, fetchPapersStream, fetchPendingPaperIds, fetchSettings, fetchPaper } from './services/api'
import { getLogger } from './utils/logger'

const logger = getLogger('App')
import AppSidebar from './components/layout/AppSidebar.vue'
import PaperCard from './components/paper/PaperCard.vue'
import ArxivImportModal from './components/ArxivImportModal.vue'

const papers = ref<Paper[]>([])
const stats = ref<Stats | null>(null)
const settings = ref<AppSettings | null>(null)
const loading = ref(false)
const fetching = ref(false)
const batchProcessing = ref(false)
const error = ref<string | null>(null)
const showImportModal = ref(false)

// Batch processing queue state
const MAX_CONCURRENT = 3
const processingQueue = ref<number[]>([])  // Queue of paper IDs waiting to process
const processingPaperIds = ref<Set<number>>(new Set())  // Currently processing paper IDs

const relevanceFilter = ref<FilterType>('all')
const statusFilter = ref<StatusFilter>('all')

const focusKeywords = computed(() => {
  if (!settings.value) return []
  if (settings.value.focus_keywords && settings.value.focus_keywords.length > 0) {
    return settings.value.focus_keywords
  }
  if (!settings.value.research_focus) return []
  return settings.value.research_focus
    .split(/[;]+/)
    .map((keyword) => keyword.trim())
    .filter(Boolean)
})

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

async function loadData() {
  loading.value = true
  error.value = null

  try {
    const [papersData, statsData, settingsData] = await Promise.all([
      fetchPapers({ limit: 100 }),
      fetchStats(),
      fetchSettings(), // Fetch settings
    ])
    papers.value = papersData
    stats.value = statsData
    settings.value = settingsData // Update settings ref
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load data'
    logger.error('Failed to load data', e)
  } finally {
    loading.value = false
  }
}

async function handleFetch() {
  if (fetching.value || batchProcessing.value) return

  fetching.value = true
  error.value = null

  fetchPapersStream({
    onDone: async (event) => {
      fetching.value = false
      await loadData()

      // Auto-trigger batch processing if there are new papers to process
      if (event.saved > 0) {
        // Small delay to ensure UI updates before batch starts
        setTimeout(() => {
          handleBatchProcess()
        }, 500)
      }
    },
    onError: (err) => {
      error.value = err.message || 'Failed to fetch papers'
      fetching.value = false
    },
  })
}

async function handleBatchProcess() {
  if (batchProcessing.value) return

  batchProcessing.value = true
  error.value = null

  try {
    // Fetch all pending paper IDs
    const pendingIds = await fetchPendingPaperIds()

    if (pendingIds.length === 0) {
      batchProcessing.value = false
      return
    }

    // Initialize queue with all pending papers
    processingQueue.value = [...pendingIds]
    processingPaperIds.value = new Set()

    // Start processing up to MAX_CONCURRENT papers
    startNextBatch()
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to start batch processing'
    batchProcessing.value = false
  }
}

function startNextBatch() {
  // Fill up to MAX_CONCURRENT processing slots
  while (
    processingPaperIds.value.size < MAX_CONCURRENT &&
    processingQueue.value.length > 0
  ) {
    const nextId = processingQueue.value.shift()!
    processingPaperIds.value = new Set([...processingPaperIds.value, nextId])
  }

  // If nothing is processing, batch is complete
  if (processingPaperIds.value.size === 0) {
    batchProcessing.value = false
    loadData()
  }
}

function handleProcessingDone(paperId: number, _success: boolean) {
  // Remove from processing set
  const newSet = new Set(processingPaperIds.value)
  newSet.delete(paperId)
  processingPaperIds.value = newSet

  // Start next paper in queue IMMEDIATELY
  // Note: loadData() is already called by the PaperCard's @refresh event
  startNextBatch()
}

onMounted(async () => {
  await loadData()

  // Auto-recover stuck papers: if any papers have processing_status === "processing"
  // but we have no active streams, trigger batch processing to reset and reprocess them.
  // The backend /papers/pending endpoint will reset stuck papers to "pending".
  const stuckPapers = papers.value.filter(
    p => p.processing_status === 'processing' && !p.is_processed
  )
  if (stuckPapers.length > 0 && !batchProcessing.value) {
    logger.info(`Auto-recovery: found ${stuckPapers.length} stuck papers, triggering batch process`)
    setTimeout(() => handleBatchProcess(), 500)
  }
})

function handleSettingsSaved() {
  loadData() // Reload all data including papers and settings
}

function handlePaperDeleted(paperId: number) {
  // Remove paper from list immediately for hot reload
  papers.value = papers.value.filter(p => p.id !== paperId)
  // Update stats
  if (stats.value) {
    stats.value.total_papers = Math.max(0, stats.value.total_papers - 1)
  }
}

// Hot reload: update a single paper in place without reordering the list
async function updatePaperById(paperId: number) {
  try {
    const updatedPaper = await fetchPaper(paperId)
    const index = papers.value.findIndex(p => p.id === paperId)
    if (index !== -1) {
      // Update paper in place, preserving list order
      papers.value[index] = updatedPaper
    }
    // Also update stats since paper is now processed
    const newStats = await fetchStats()
    stats.value = newStats
  } catch (e) {
    logger.error('Failed to update paper', e)
  }
}

async function handlePaperImported(paperId: number, isNew: boolean) {
  // Reload data to show the new paper
  await loadData()

  // If it's a new paper, trigger batch processing to analyze it
  if (isNew) {
    // Add the paper to the processing queue
    processingQueue.value = [paperId]
    processingPaperIds.value = new Set()
    batchProcessing.value = true
    startNextBatch()
  }
}
</script>

<template>
  <div class="flex min-h-screen bg-[var(--color-paper-50)]">
    <!-- Sidebar -->
    <AppSidebar
      :stats="stats"
      :settings="settings"
      :relevance-filter="relevanceFilter"
      :status-filter="statusFilter"
      :loading="fetching"
      :batch-processing="batchProcessing"
      @update:relevance-filter="relevanceFilter = $event"
      @update:status-filter="statusFilter = $event"
      @fetch="handleFetch"
      @batch-process="handleBatchProcess"
      @import="showImportModal = true"
      @settings-saved="handleSettingsSaved"
    />

    <!-- Main Content -->
    <main class="flex-1 min-w-0">
      <!-- Header -->
      <header class="sticky top-0 z-10 bg-[var(--color-paper-50)]/80 backdrop-blur-sm border-b border-[var(--color-paper-200)] px-8 py-4">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="font-display text-xl font-semibold text-[var(--color-ink-900)]">
              Research Feed
            </h2>
            <p class="text-sm text-[var(--color-ink-400)]">
              {{ filteredPapers.length }} papers
              <span v-if="relevanceFilter !== 'all' || statusFilter !== 'all'">
                (filtered)
              </span>
            </p>
          </div>

          <!-- Search (placeholder) -->
          <div class="relative">
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
        <div class="mt-3 flex flex-wrap items-center gap-2">
          <span class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)]">
            Research Focus
          </span>
          <div v-if="focusKeywords.length > 0" class="flex flex-wrap gap-2">
            <span
              v-for="keyword in focusKeywords"
              :key="keyword"
              class="px-2.5 py-1 rounded-md bg-[var(--color-paper-100)] border border-[var(--color-paper-200)] text-xs text-[var(--color-ink-700)] font-mono shadow-sm"
            >
              {{ keyword }}
            </span>
          </div>
          <span v-else class="text-xs text-[var(--color-ink-400)] italic">
            No focus set. Default query used.
          </span>
        </div>
      </header>

      <!-- Content Area -->
      <div class="p-8">
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
            :auto-process="processingPaperIds.has(paper.id)"
            class="animate-slide-up"
            :style="{ animationDelay: `${filteredPapers.indexOf(paper) * 50}ms` }"
            @refresh="updatePaperById"
            @delete="handlePaperDeleted"
            @processing-done="handleProcessingDone"
          />
        </div>
      </div>
    </main>

    <!-- Import Modal -->
    <ArxivImportModal
      :show="showImportModal"
      @close="showImportModal = false"
      @imported="handlePaperImported"
    />
  </div>
</template>
