<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { AppSettings, AutofillFields, Direction } from '../../types/paper'
import { useAutofillStore } from '../../stores/autofill'
import { getStreamErrorMessage } from '../../services/api'
import { providerNeedsKey } from '../../utils/settings'

const props = defineProps<{
  directionKey: string
  direction: Direction
  settings: AppSettings  // for the reasoning model shown in the (unsaved) form
}>()

const emit = defineEmits<{
  close: []
  apply: [fields: AutofillFields]
}>()

const store = useAutofillStore()
const run = computed(() => store.get(props.directionKey))
const description = ref(run.value.description)
const showThinking = ref(false)
const openRound = ref<number | null>(null)

const reasoning = computed(() => props.settings.pipeline.reasoning)
const provider = computed(() => props.settings.providers.find(p => p.id === reasoning.value.provider_id))
const modelProblem = computed(() => {
  if (!provider.value || !reasoning.value.model) return '请先在「解析流程」中选择推理模型'
  if (providerNeedsKey(provider.value)) return `请先在「模型服务」中填写 ${provider.value.name} 的 API Key`
  return ''
})

// Elapsed timer while running
const now = ref(Date.now())
const clock = setInterval(() => { now.value = Date.now() }, 1000)
onUnmounted(() => clearInterval(clock))
const elapsed = computed(() =>
  run.value.status === 'running' ? Math.max(0, Math.floor((now.value - run.value.startedAt) / 1000)) : 0
)

const fields = computed(() => run.value.result?.fields ?? null)
const bestRound = computed(() =>
  run.value.result ? run.value.rounds.find(r => r.round === run.value.result!.best_round) : null
)

watch(() => run.value.rounds.length, (n) => { if (n) openRound.value = run.value.rounds[n - 1].round })

function start() {
  if (!description.value.trim() || modelProblem.value) return
  store.start(props.directionKey, description.value.trim(), provider.value, reasoning.value.model)
}

function apply() {
  if (!fields.value) return
  emit('apply', fields.value)
  store.clear(props.directionKey)
  emit('close')
}

function pct(value: number | null) {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}
</script>

<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-[60] flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/25 backdrop-blur-[2px]" @click="emit('close')"></div>

      <div class="relative bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[88vh] flex flex-col overflow-hidden animate-slide-up">
        <!-- Header -->
        <div class="px-6 py-4 border-b border-gray-100 flex items-start justify-between gap-4">
          <div>
            <h3 class="text-base font-semibold text-[var(--color-ink-900)] flex items-center gap-2">
              <span>✨</span> Fill with AI「{{ direction.name || '研究方向' }}」
            </h3>
            <p class="text-xs text-gray-500 mt-1">
              用大白话描述你的研究，推理模型会生成分类、检索式、研究 Idea 与评分标准，并在 arXiv 上多轮实测检索式。
            </p>
          </div>
          <button class="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600" @click="emit('close')">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="px-6 py-5 overflow-y-auto flex-1 space-y-5">
          <!-- Description -->
          <section>
            <textarea
              v-model="description"
              rows="5"
              :disabled="run.status === 'running'"
              class="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none disabled:bg-gray-50 disabled:text-gray-500"
              placeholder="例如：我在做视频生成模型的推理加速，长视频生成太慢、显存也不够。想利用注意力头的稀疏性和相邻去噪步骤的冗余，做 KV cache 复用或 token 剪枝，速度快几倍但画质基本不掉。"
            ></textarea>
            <div class="mt-1.5 flex items-center justify-between text-[11px] text-gray-400">
              <span v-if="modelProblem" class="text-amber-700">{{ modelProblem }}</span>
              <span v-else>模型：{{ provider?.name }} · {{ reasoning.model }}</span>
              <span>{{ description.trim().length }} 字</span>
            </div>
          </section>

          <!-- Progress -->
          <section v-if="run.status !== 'idle'" class="space-y-3">
            <div
              v-if="run.status === 'running'"
              class="flex items-center gap-2 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2"
            >
              <svg class="w-4 h-4 animate-spin flex-shrink-0" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span class="flex-1 truncate">{{ run.message }}</span>
              <span class="font-mono text-xs text-amber-600">{{ elapsed }}s</span>
            </div>
            <div
              v-else-if="run.status === 'error' && run.error"
              class="text-sm text-red-700 bg-red-50 border border-red-200 rounded-lg px-3 py-2 break-all"
            >
              {{ getStreamErrorMessage(run.error) }}
            </div>

            <!-- Keyword test rounds -->
            <div v-if="run.rounds.length" class="space-y-2">
              <h4 class="text-xs font-semibold uppercase tracking-wider text-gray-400">检索式实测</h4>
              <div
                v-for="round in run.rounds"
                :key="round.round"
                class="border rounded-lg overflow-hidden"
                :class="run.result?.best_round === round.round ? 'border-emerald-300' : 'border-gray-200'"
              >
                <button
                  class="w-full flex items-center gap-3 px-3 py-2 text-left text-xs hover:bg-gray-50"
                  @click="openRound = openRound === round.round ? null : round.round"
                >
                  <span class="font-semibold text-gray-700">第 {{ round.round }} 轮</span>
                  <span class="text-gray-500">近 7 天 {{ round.weekly }}{{ round.weekly_capped ? '+' : '' }} 篇</span>
                  <span class="text-gray-500">相关率 {{ pct(round.precision) }}</span>
                  <span
                    class="ml-auto px-1.5 py-0.5 rounded text-[10px] font-medium"
                    :class="round.acceptable ? 'bg-emerald-50 text-emerald-700' : 'bg-gray-100 text-gray-500'"
                  >
                    {{ round.acceptable ? '达标' : '未达标' }}
                  </span>
                  <span v-if="run.result?.best_round === round.round" class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-600 text-white">
                    采用
                  </span>
                </button>
                <div v-if="openRound === round.round" class="px-3 pb-3 space-y-2 text-xs border-t border-gray-100 bg-gray-50/50">
                  <p class="pt-2 font-mono text-[11px] text-gray-600 break-all">{{ round.research_focus }}</p>
                  <p class="text-gray-600">{{ round.assessment }}</p>
                  <ul v-if="round.samples?.length" class="space-y-0.5">
                    <li v-for="(sample, i) in round.samples" :key="i" class="flex gap-1.5 text-gray-600">
                      <span :class="sample.relevant ? 'text-emerald-600' : 'text-gray-300'">{{ sample.relevant ? '✓' : '✗' }}</span>
                      <span class="truncate">{{ sample.title }}</span>
                    </li>
                  </ul>
                </div>
              </div>
            </div>

            <!-- Model reasoning (collapsed) -->
            <div v-if="run.thinking" class="text-xs">
              <button class="text-gray-400 hover:text-gray-600" @click="showThinking = !showThinking">
                {{ showThinking ? '▾' : '▸' }} 模型思考过程
              </button>
              <pre v-if="showThinking" class="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] text-gray-500 bg-gray-50 rounded-lg p-2">{{ run.thinking }}</pre>
            </div>
          </section>

          <!-- Result preview -->
          <section v-if="fields" class="space-y-3 border-t border-gray-100 pt-4">
            <h4 class="text-xs font-semibold uppercase tracking-wider text-gray-400 flex items-center gap-2">
              结果预览
              <span v-if="bestRound" class="normal-case font-normal tracking-normal text-gray-500">
                · 采用第 {{ bestRound.round }} 轮检索式（近 7 天 {{ bestRound.weekly }} 篇，相关率 {{ pct(bestRound.precision) }}{{ run.result?.acceptable ? '' : '，未完全达到 70% 目标' }}）
              </span>
            </h4>
            <div class="flex flex-wrap gap-1.5">
              <span v-for="code in fields.arxiv_categories" :key="code" class="px-2 py-0.5 rounded-md bg-blue-50 text-blue-700 text-xs font-mono">{{ code }}</span>
            </div>
            <p class="font-mono text-[11px] text-gray-700 bg-gray-50 rounded-lg p-2 break-all">{{ fields.research_focus }}</p>
            <pre class="whitespace-pre-wrap text-xs text-gray-700 bg-gray-50 rounded-lg p-2 max-h-48 overflow-y-auto font-sans">{{ fields.research_idea }}</pre>
            <details class="text-xs">
              <summary class="cursor-pointer text-gray-500">分析提示词（角色与评分标准）</summary>
              <pre class="mt-1 whitespace-pre-wrap text-gray-600 bg-gray-50 rounded-lg p-2 max-h-40 overflow-y-auto font-sans">{{ fields.system_prompt }}</pre>
            </details>
          </section>
        </div>

        <!-- Footer -->
        <div class="px-6 py-3 border-t border-gray-100 bg-gray-50/50 flex items-center justify-end gap-2">
          <p v-if="run.status === 'running'" class="mr-auto text-[11px] text-gray-400">关闭窗口不会中断，结果会保留在这里。</p>
          <button
            v-if="run.status === 'running'"
            class="px-3 py-1.5 text-sm text-gray-600 bg-white border border-gray-200 rounded-lg hover:bg-gray-50"
            @click="store.cancel(directionKey)"
          >
            停止
          </button>
          <button
            v-else
            :disabled="!description.trim() || !!modelProblem"
            class="px-3 py-1.5 text-sm font-medium rounded-lg border transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            :class="fields
              ? 'text-gray-700 bg-white border-gray-200 hover:bg-gray-50'
              : 'text-white bg-[var(--color-ink-900)] border-[var(--color-ink-900)] hover:bg-[var(--color-ink-700)]'"
            @click="start"
          >
            {{ run.status === 'idle' ? '开始生成' : '重新生成' }}
          </button>
          <button
            v-if="fields && run.status !== 'running'"
            class="px-3 py-1.5 text-sm font-medium text-white bg-[var(--color-ink-900)] rounded-lg hover:bg-[var(--color-ink-700)]"
            @click="apply"
          >
            应用到此方向
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
