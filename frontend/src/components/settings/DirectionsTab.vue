<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import type { AppSettings, ArxivOption, AutofillFields, Direction, DirectionSummary } from '../../types/paper'
import { fetchDirections } from '../../services/api'
import { useAutofillStore } from '../../stores/autofill'
import DirectionEditor from './DirectionEditor.vue'
import AutofillDialog from './AutofillDialog.vue'

const settings = defineModel<AppSettings>('settings', { required: true })

const props = defineProps<{
  arxivOptions: ArxivOption[]
  initialDirectionId?: number | null
  newDirection?: boolean
}>()

const autofill = useAutofillStore()
const counts = ref<Record<number, DirectionSummary>>({})
const activeKey = ref('')
const dialogKey = ref<string | null>(null)
const confirmingDelete = ref(false)
let newCounter = 0

const directions = computed(() => settings.value.directions)
const active = computed(() => directions.value.find(d => d._key === activeKey.value) ?? directions.value[0])
const dialogDirection = computed(() => directions.value.find(d => d._key === dialogKey.value) ?? null)

function addDirection() {
  newCounter += 1
  const direction: Direction = {
    id: null,
    name: `研究方向 ${directions.value.length + 1}`,
    arxiv_categories: ['cs.CV', 'cs.LG'],
    research_focus: '',
    focus_keywords: [],
    research_idea: '',
    system_prompt: '',
    _key: `new-${newCounter}`,
  }
  directions.value.push(direction)
  activeKey.value = direction._key!
}

function removeActive() {
  if (directions.value.length <= 1 || !active.value) return
  const index = directions.value.indexOf(active.value)
  directions.value.splice(index, 1)
  activeKey.value = directions.value[Math.max(0, index - 1)]._key!
  confirmingDelete.value = false
}

function applyFields(fields: AutofillFields) {
  const direction = dialogDirection.value
  if (!direction) return
  direction.arxiv_categories = [...fields.arxiv_categories]
  direction.research_focus = fields.research_focus
  direction.research_idea = fields.research_idea
  direction.system_prompt = fields.system_prompt
}

function runState(direction: Direction) {
  return autofill.runs[direction._key!]?.status ?? 'idle'
}

watch(activeKey, () => { confirmingDelete.value = false })

// For the modal footer's "Fill with AI" button (acts on the selected direction)
const autofillStatus = computed(() => (active.value ? runState(active.value) : 'idle'))

function openAutofill() {
  if (active.value) dialogKey.value = active.value._key!
}

defineExpose({ openAutofill, autofillStatus })

onMounted(async () => {
  activeKey.value =
    directions.value.find(d => d.id === props.initialDirectionId)?._key ?? directions.value[0]?._key ?? ''
  if (props.newDirection) addDirection()
  try {
    counts.value = Object.fromEntries((await fetchDirections()).map(d => [d.id, d]))
  } catch {
    // counts are informational only
  }
})
</script>

<template>
  <div class="flex flex-col min-h-full">
    <!-- Direction sub-tabs -->
    <div class="flex items-center gap-1.5 overflow-x-auto pb-3 mb-5 border-b border-gray-100">
      <button
        v-for="direction in directions"
        :key="direction._key"
        class="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border transition-colors"
        :class="direction._key === active?._key
          ? 'bg-blue-50 text-blue-700 border-blue-200 font-medium'
          : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'"
        @click="activeKey = direction._key!"
      >
        <span
          v-if="runState(direction) === 'running'"
          class="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse"
          title="AI 填写中"
        ></span>
        <span
          v-else-if="runState(direction) === 'done'"
          class="w-1.5 h-1.5 rounded-full bg-emerald-500"
          title="AI 结果待应用"
        ></span>
        <span class="max-w-[140px] truncate">{{ direction.name || '未命名' }}</span>
        <span v-if="direction.id == null" class="text-[10px] text-blue-400">新</span>
      </button>
      <button
        class="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg border border-dashed border-gray-300 text-gray-400 hover:text-gray-700 hover:border-gray-400 transition-colors"
        title="添加研究方向"
        @click="addDirection"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v14m-7-7h14" />
        </svg>
      </button>
    </div>

    <!-- The selected direction (each page edits only its own direction) -->
    <DirectionEditor
      v-if="active"
      :key="active._key"
      v-model:direction="settings.directions[directions.indexOf(active)]"
      :arxiv-options="arxivOptions"
      class="flex-1"
    />

    <!-- Delete (the AI fill button lives in the modal footer, next to Cancel / Save) -->
    <div v-if="active && directions.length > 1" class="mt-6 pt-4 border-t border-gray-100 flex items-center justify-end gap-2 text-xs">
      <template v-if="confirmingDelete">
        <span class="text-gray-500">
          保存后将删除此方向<span v-if="active.id != null && counts[active.id]?.total">及其 {{ counts[active.id].total }} 篇论文</span>
        </span>
        <button class="px-2.5 py-1 rounded-md text-gray-600 border border-gray-200 hover:bg-gray-50" @click="confirmingDelete = false">取消</button>
        <button class="px-2.5 py-1 rounded-md text-white bg-red-600 hover:bg-red-700" @click="removeActive">删除</button>
      </template>
      <button
        v-else
        class="px-2.5 py-1 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors"
        @click="confirmingDelete = true"
      >
        删除此方向
      </button>
    </div>

    <AutofillDialog
      v-if="dialogDirection"
      :direction-key="dialogDirection._key!"
      :direction="dialogDirection"
      :settings="settings"
      @close="dialogKey = null"
      @apply="applyFields"
    />
  </div>
</template>
