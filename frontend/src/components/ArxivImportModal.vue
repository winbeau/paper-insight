<script setup lang="ts">
import { ref, computed } from 'vue'
import { importPaper } from '../services/api'

defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  close: []
  imported: [paperId: number, isNew: boolean]
}>()

const arxivUrl = ref('')
const isImporting = ref(false)
const error = ref<string | null>(null)
const successResult = ref<{ title: string; arxivId: string; isNew: boolean } | null>(null)

// Validate URL format
const isValidUrl = computed(() => {
  if (!arxivUrl.value.trim()) return false
  // Match arXiv URLs or IDs
  const pattern = /(\d{4}\.\d{4,5}(?:v\d+)?)|arxiv\.org/i
  return pattern.test(arxivUrl.value)
})

async function handleImport() {
  if (!arxivUrl.value.trim() || isImporting.value) return

  isImporting.value = true
  error.value = null
  successResult.value = null

  try {
    const result = await importPaper(arxivUrl.value.trim())
    successResult.value = {
      title: result.title,
      arxivId: result.arxiv_id,
      isNew: result.is_new,
    }

    // Auto-close and emit after short delay
    setTimeout(() => {
      emit('imported', result.paper_id, result.is_new)
      handleClose()
    }, 1500)
  } catch (e: unknown) {
    if (e && typeof e === 'object' && 'response' in e) {
      const axiosError = e as { response?: { data?: { detail?: string } } }
      error.value = axiosError.response?.data?.detail || 'Failed to import paper'
    } else {
      error.value = e instanceof Error ? e.message : 'Failed to import paper'
    }
  } finally {
    isImporting.value = false
  }
}

function handleClose() {
  arxivUrl.value = ''
  error.value = null
  successResult.value = null
  emit('close')
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && isValidUrl.value && !isImporting.value) {
    handleImport()
  }
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="show"
      class="fixed inset-0 z-[10000] flex items-center justify-center p-4"
    >
      <!-- Backdrop -->
      <Transition
        appear
        enter-active-class="transition-opacity duration-300 ease-out"
        enter-from-class="opacity-0"
        enter-to-class="opacity-100"
        leave-active-class="transition-opacity duration-200 ease-in"
        leave-from-class="opacity-100"
        leave-to-class="opacity-0"
      >
        <div
          v-if="show"
          class="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
          @click="handleClose"
        ></div>
      </Transition>

      <!-- Modal -->
      <Transition
        appear
        enter-active-class="transition-all duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)]"
        enter-from-class="opacity-0 scale-90"
        enter-to-class="opacity-100 scale-100"
        leave-active-class="transition-all duration-200 ease-in"
        leave-from-class="opacity-100 scale-100"
        leave-to-class="opacity-0 scale-95"
      >
        <div
          v-if="show"
          class="relative bg-white rounded-2xl shadow-[0_25px_50px_-12px_rgba(0,0,0,0.25)] max-w-lg w-full overflow-hidden ring-1 ring-black/5"
          @click.stop
        >
          <!-- Header with gradient accent -->
          <div class="relative px-6 pt-6 pb-5">
            <div class="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-500"></div>
            <div class="flex items-start gap-4">
              <div class="flex-shrink-0 w-12 h-12 rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/25">
                <svg class="w-6 h-6 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                </svg>
              </div>
              <div class="flex-1 min-w-0">
                <h3 class="text-xl font-semibold text-gray-900 tracking-tight">Import from arXiv</h3>
                <p class="text-sm text-gray-500 mt-0.5">Paste an arXiv link or ID to import a paper</p>
              </div>
              <button
                class="flex-shrink-0 p-2 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                @click="handleClose"
              >
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>

          <!-- Content -->
          <div class="px-6 pb-5">
            <!-- Input -->
            <div class="relative">
              <input
                v-model="arxivUrl"
                type="text"
                placeholder="https://arxiv.org/abs/2301.12345 or 2301.12345"
                class="w-full px-4 py-3 bg-gray-50 border border-gray-200 rounded-xl text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                :class="{ 'border-red-300 focus:ring-red-500/20 focus:border-red-500': error }"
                :disabled="isImporting || !!successResult"
                @keydown="handleKeydown"
              />
              <div
                v-if="arxivUrl && isValidUrl && !error && !successResult"
                class="absolute right-3 top-1/2 -translate-y-1/2"
              >
                <svg class="w-5 h-5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                </svg>
              </div>
            </div>

            <!-- Error message -->
            <div v-if="error" class="mt-3 p-3 bg-red-50 border border-red-100 rounded-lg">
              <div class="flex items-start gap-2">
                <svg class="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p class="text-sm text-red-700">{{ error }}</p>
              </div>
            </div>

            <!-- Success message -->
            <div v-if="successResult" class="mt-3 p-4 bg-green-50 border border-green-100 rounded-lg">
              <div class="flex items-start gap-3">
                <div class="flex-shrink-0 w-8 h-8 rounded-full bg-green-100 flex items-center justify-center">
                  <svg class="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-medium text-green-800">
                    {{ successResult.isNew ? 'Paper imported successfully!' : 'Paper already exists' }}
                  </p>
                  <p class="text-xs text-green-600 mt-1 line-clamp-2">{{ successResult.title }}</p>
                  <span class="inline-flex items-center px-2 py-0.5 mt-2 rounded-md bg-white border border-green-200 text-xs font-mono text-green-700">
                    {{ successResult.arxivId }}
                  </span>
                </div>
              </div>
            </div>

            <!-- Help text -->
            <p v-if="!error && !successResult" class="mt-3 text-xs text-gray-500">
              Supported formats: <code class="px-1 py-0.5 bg-gray-100 rounded">https://arxiv.org/abs/2301.12345</code>,
              <code class="px-1 py-0.5 bg-gray-100 rounded">2301.12345</code>
            </p>
          </div>

          <!-- Footer -->
          <div class="px-6 py-4 bg-gray-50/80 border-t border-gray-100 flex items-center justify-end gap-3">
            <button
              class="px-5 py-2.5 text-sm font-medium text-gray-600 hover:text-gray-900 hover:bg-white rounded-lg border border-transparent hover:border-gray-200 transition-all duration-150"
              :disabled="isImporting"
              @click="handleClose"
            >
              {{ successResult ? 'Close' : 'Cancel' }}
            </button>
            <button
              v-if="!successResult"
              class="px-5 py-2.5 text-sm font-medium text-white bg-gradient-to-r from-blue-500 to-indigo-600 hover:from-blue-600 hover:to-indigo-700 rounded-lg shadow-md shadow-blue-500/25 hover:shadow-lg hover:shadow-blue-500/30 transition-all duration-150 flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none"
              :disabled="!isValidUrl || isImporting"
              @click="handleImport"
            >
              <svg v-if="isImporting" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>{{ isImporting ? 'Importing...' : 'Import Paper' }}</span>
            </button>
          </div>
        </div>
      </Transition>
    </div>
  </Teleport>
</template>
