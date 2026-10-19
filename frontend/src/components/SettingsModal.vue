<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import type { AppSettings, ArxivOption } from '../types/paper'
import { fetchConstants, fetchSettings, updateSettings } from '../services/api'
import { getLogger } from '../utils/logger'
import { analysisSetupProblem } from '../utils/settings'
import DirectionsTab from './settings/DirectionsTab.vue'
import ProvidersTab from './settings/ProvidersTab.vue'
import PipelineTab from './settings/PipelineTab.vue'
import HistoryTab from './settings/HistoryTab.vue'

const logger = getLogger('SettingsModal')

type TabKey = 'research' | 'providers' | 'pipeline' | 'history'

const props = defineProps<{
  initialTab?: TabKey
  initialDirectionId?: number | null
  newDirection?: boolean
}>()

const emit = defineEmits(['close'])

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: 'research', label: '研究方向' },
  { key: 'providers', label: '模型服务' },
  { key: 'pipeline', label: '解析流程' },
  { key: 'history', label: '历史记录' },
]

const activeTab = ref<TabKey>(props.initialTab ?? 'research')
const directionsTab = ref<InstanceType<typeof DirectionsTab> | null>(null)
const loading = ref(true)
const saving = ref(false)
const saveError = ref('')
const arxivOptions = ref<ArxivOption[]>([])
const settings = ref<AppSettings | null>(null)

const setupProblem = computed(() => analysisSetupProblem(settings.value))

onMounted(async () => {
  try {
    const [constants, current] = await Promise.all([fetchConstants(), fetchSettings()])
    arxivOptions.value = constants.arxiv_options
    // Stable client keys: the per-direction AI fill runs are keyed by them
    for (const direction of current.directions) direction._key = `d${direction.id}`
    settings.value = current
  } catch (e) {
    logger.error('Failed to load settings', e)
    saveError.value = '读取设置失败'
  } finally {
    loading.value = false
  }
})

async function saveSettings() {
  if (!settings.value) return
  saving.value = true
  saveError.value = ''
  try {
    await updateSettings(settings.value)
    emit('close')
  } catch (e) {
    logger.error('Failed to save settings', e)
    saveError.value = (e as Error).message || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <!-- Backdrop -->
      <div
        class="absolute inset-0 bg-black/20 backdrop-blur-sm transition-opacity"
        @click="$emit('close')"
      ></div>

      <!-- Modal Content -->
      <div class="relative bg-white rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-hidden flex flex-col animate-slide-up">
        <!-- Header -->
        <div class="px-6 pt-4 border-b border-gray-100 bg-gray-50/50">
          <div class="flex items-center justify-between">
            <h2 class="text-lg font-display font-semibold text-[var(--color-ink-900)]">Settings</h2>
            <button
              @click="$emit('close')"
              class="p-2 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <nav class="flex gap-1 mt-2 -mb-px">
            <button
              v-for="tab in tabs"
              :key="tab.key"
              class="px-3 py-2 text-sm font-medium border-b-2 transition-colors"
              :class="activeTab === tab.key
                ? 'border-[var(--color-ink-900)] text-[var(--color-ink-900)]'
                : 'border-transparent text-gray-500 hover:text-gray-800'"
              @click="activeTab = tab.key"
            >
              {{ tab.label }}
              <span
                v-if="(tab.key === 'pipeline' && setupProblem?.kind === 'model') || (tab.key === 'providers' && setupProblem?.kind === 'key')"
                class="inline-block w-1.5 h-1.5 rounded-full bg-red-500 align-middle ml-1"
              ></span>
            </button>
          </nav>
        </div>

        <!-- Body -->
        <div class="p-6 overflow-y-auto flex-1">
          <div v-if="loading" class="flex justify-center py-12">
            <svg class="w-8 h-8 animate-spin text-gray-300" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>

          <template v-else-if="settings">
            <!-- v-show: keep the selected direction while visiting the other tabs -->
            <DirectionsTab
              v-show="activeTab === 'research'"
              ref="directionsTab"
              v-model:settings="settings"
              :arxiv-options="arxivOptions"
              :initial-direction-id="initialDirectionId"
              :new-direction="newDirection"
            />
            <ProvidersTab v-if="activeTab === 'providers'" v-model:settings="settings" />
            <PipelineTab v-else-if="activeTab === 'pipeline'" v-model:settings="settings" />
            <HistoryTab v-else-if="activeTab === 'history'" />
          </template>
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex items-center gap-3">
          <!-- AI fill for the selected research direction -->
          <button
            v-if="activeTab === 'research' && settings && directionsTab"
            class="flex-shrink-0 flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg border transition-colors"
            :class="directionsTab.autofillStatus === 'running'
              ? 'text-amber-800 bg-amber-50 border-amber-200'
              : directionsTab.autofillStatus === 'done'
                ? 'text-emerald-800 bg-emerald-50 border-emerald-200'
                : 'text-indigo-700 bg-indigo-50 border-indigo-200 hover:bg-indigo-100'"
            @click="directionsTab.openAutofill()"
          >
            <svg v-if="directionsTab.autofillStatus === 'running'" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span v-else>✨</span>
            {{ directionsTab.autofillStatus === 'running' ? 'AI filling…' : directionsTab.autofillStatus === 'done' ? 'Review AI result' : 'Fill with AI' }}
          </button>
          <p class="flex-1 min-w-0 truncate text-xs">
            <span v-if="saveError" class="text-red-600">{{ saveError }}</span>
            <span v-else-if="setupProblem?.kind === 'key'" class="text-amber-700">
              请在「模型服务」中填写 {{ setupProblem.provider.name }} 的 API Key。
            </span>
            <span v-else-if="setupProblem && !loading" class="text-amber-700">
              尚未配置推理模型，论文将无法分析。
            </span>
          </p>
          <button
            @click="$emit('close')"
            class="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          <button
            @click="saveSettings"
            :disabled="saving || !settings"
            class="px-4 py-2 text-sm font-medium text-white bg-[var(--color-ink-900)] rounded-lg hover:bg-[var(--color-ink-700)] transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <svg v-if="saving" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            {{ saving ? 'Saving...' : 'Save Changes' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
