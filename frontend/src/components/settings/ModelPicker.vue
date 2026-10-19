<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { ModelRef, Provider, ProviderTestResult } from '../../types/paper'
import { listProviderModels, testProvider } from '../../services/api'

const modelRef = defineModel<ModelRef>({ required: true })

const props = defineProps<{
  providers: Provider[]
  kind: 'chat' | 'vision'
  placeholder?: string
}>()

const models = ref<string[]>([])
const loadingModels = ref(false)
const modelsError = ref('')
const testing = ref(false)
const testResult = ref<ProviderTestResult | null>(null)
const listId = `models-${Math.random().toString(16).slice(2)}`

const provider = computed(() => props.providers.find(p => p.id === modelRef.value.provider_id) ?? null)

async function loadModels() {
  if (!provider.value?.base_url) return
  loadingModels.value = true
  modelsError.value = ''
  try {
    const result = await listProviderModels(provider.value)
    models.value = result.models
    if (!result.ok) modelsError.value = result.error || '无法获取模型列表'
  } catch (e) {
    modelsError.value = (e as Error).message
  } finally {
    loadingModels.value = false
  }
}

async function runTest() {
  if (!provider.value || !modelRef.value.model) return
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testProvider(provider.value, modelRef.value.model, props.kind)
  } catch (e) {
    testResult.value = { ok: false, error: (e as Error).message }
  } finally {
    testing.value = false
  }
}

watch(
  () => modelRef.value.provider_id,
  () => {
    models.value = []
    testResult.value = null
    loadModels()
  },
  { immediate: true },
)
watch(() => modelRef.value.model, () => { testResult.value = null })
</script>

<template>
  <div class="space-y-2">
    <div class="grid grid-cols-1 sm:grid-cols-[180px_1fr_auto] gap-2 items-center">
      <select
        v-model="modelRef.provider_id"
        class="px-2 py-1.5 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
      >
        <option value="">— 选择模型服务 —</option>
        <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name || p.base_url }}</option>
      </select>
      <div class="relative">
        <input
          v-model.trim="modelRef.model"
          :list="listId"
          :disabled="!provider"
          class="w-full px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm font-mono focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none disabled:bg-gray-50"
          :placeholder="placeholder || '模型名称'"
        />
        <datalist :id="listId">
          <option v-for="m in models" :key="m" :value="m" />
        </datalist>
        <button
          v-if="provider"
          class="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700"
          :title="loadingModels ? '加载中…' : `刷新模型列表（${models.length}）`"
          @click="loadModels"
        >
          <svg class="w-3.5 h-3.5" :class="{ 'animate-spin': loadingModels }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>
      <button
        :disabled="!provider || !modelRef.model || testing"
        class="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
        @click="runTest"
      >
        {{ testing ? '测试中…' : '测试' }}
      </button>
    </div>
    <p v-if="testResult?.ok" class="text-xs text-emerald-600">
      ✓ 可用（{{ testResult.latency_ms }} ms）：{{ testResult.reply }}
    </p>
    <p v-else-if="testResult" class="text-xs text-red-600 break-all">✗ {{ testResult.error }}</p>
    <p v-else-if="modelsError && provider" class="text-[11px] text-gray-400">模型列表不可用：{{ modelsError }}（可手动输入模型名）</p>
    <p v-else-if="providers.length === 0" class="text-[11px] text-gray-400">请先在「模型服务」中添加服务。</p>
  </div>
</template>
