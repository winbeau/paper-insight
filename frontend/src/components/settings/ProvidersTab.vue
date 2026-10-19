<script setup lang="ts">
import { ref } from 'vue'
import type { AppSettings, Provider } from '../../types/paper'
import { PROVIDER_PRESETS, newProviderId } from './presets'
import { providerNeedsKey } from '../../utils/settings'

const settings = defineModel<AppSettings>('settings', { required: true })

const showPresets = ref(false)

function addProvider(preset?: { name: string; base_url: string }) {
  settings.value.providers.push({
    id: newProviderId(),
    name: preset?.name ?? '自定义',
    base_url: preset?.base_url ?? '',
    api_key: '',
    json_mode: false,
  })
  showPresets.value = false
}

function removeProvider(provider: Provider) {
  // Steps using it become unconfigured (shown as such in the Pipeline tab)
  for (const step of [settings.value.pipeline.vision, settings.value.pipeline.reasoning]) {
    if (step.provider_id === provider.id) step.provider_id = ''
  }
  settings.value.providers = settings.value.providers.filter(p => p.id !== provider.id)
}

function presetHint(baseUrl: string): string {
  return PROVIDER_PRESETS.find(p => p.base_url === baseUrl)?.hint ?? ''
}
</script>

<template>
  <div class="space-y-8">
    <section>
      <div class="flex items-center justify-between mb-3">
        <div>
          <h3 class="text-sm font-semibold text-[var(--color-ink-900)]">模型服务</h3>
          <p class="text-xs text-gray-500 mt-0.5">
            任何兼容 OpenAI Chat Completions 接口的服务。在「解析流程」中为每个步骤选择模型。
          </p>
        </div>
        <div class="relative">
          <button
            class="px-3 py-1.5 text-xs font-medium text-white bg-[var(--color-ink-900)] rounded-lg hover:bg-[var(--color-ink-700)] transition-colors"
            @click="showPresets = !showPresets"
          >
            + 添加服务
          </button>
          <div
            v-if="showPresets"
            class="absolute right-0 mt-1 w-64 bg-white border border-gray-200 rounded-lg shadow-lg z-10 py-1"
          >
            <button
              v-for="preset in PROVIDER_PRESETS"
              :key="preset.name"
              class="w-full text-left px-3 py-2 hover:bg-gray-50"
              @click="addProvider(preset)"
            >
              <span class="block text-sm text-gray-900">{{ preset.name }}</span>
              <span class="block text-[11px] text-gray-400 truncate">{{ preset.hint || preset.base_url }}</span>
            </button>
            <button
              class="w-full text-left px-3 py-2 hover:bg-gray-50 border-t border-gray-100 text-sm text-gray-700"
              @click="addProvider()"
            >
              自定义…
            </button>
          </div>
        </div>
      </div>

      <div v-if="settings.providers.length === 0" class="text-sm text-gray-500 border border-dashed border-gray-300 rounded-lg p-6 text-center">
        还没有模型服务。添加一个（例如 DeepSeek 用于推理，阿里云百炼 / OpenAI 用于视觉识别）。
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="provider in settings.providers"
          :key="provider.id"
          class="border border-gray-200 rounded-lg p-4 space-y-3"
        >
          <div class="flex items-center gap-3">
            <input
              v-model="provider.name"
              class="flex-1 px-2 py-1 text-sm font-medium border border-transparent hover:border-gray-200 focus:border-gray-300 rounded outline-none"
              placeholder="名称"
            />
            <span v-if="presetHint(provider.base_url)" class="text-[11px] text-gray-400">
              {{ presetHint(provider.base_url) }}
            </span>
            <button
              class="p-1 text-gray-400 hover:text-red-600 rounded"
              title="删除"
              @click="removeProvider(provider)"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label class="block">
              <span class="text-[11px] font-medium text-gray-500 uppercase tracking-wider">Base URL</span>
              <input
                v-model.trim="provider.base_url"
                class="mt-1 w-full px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm font-mono focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                placeholder="https://api.example.com/v1"
              />
            </label>
            <label class="block">
              <span class="text-[11px] font-medium text-gray-500 uppercase tracking-wider">API Key</span>
              <input
                v-model.trim="provider.api_key"
                type="password"
                autocomplete="off"
                class="mt-1 w-full px-3 py-1.5 bg-white border rounded-lg text-sm font-mono focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                :class="providerNeedsKey(provider) ? 'border-amber-400' : 'border-gray-200'"
                placeholder="sk-…（本地模型可留空）"
              />
            </label>
          </div>
          <label class="flex items-center gap-2 text-xs text-gray-600">
            <input v-model="provider.json_mode" type="checkbox" class="h-3.5 w-3.5 rounded border-gray-300" />
            推理步骤使用 JSON 模式（response_format=json_object；部分推理模型不支持）
          </label>
        </div>
      </div>
      <p class="mt-3 text-xs text-gray-400">
        API Key 仅保存在本机（~/Library/Application Support/PaperInsight），界面中只显示末四位。
      </p>
    </section>

    <section>
      <h3 class="text-sm font-semibold text-[var(--color-ink-900)] mb-1">网络代理</h3>
      <p class="text-xs text-gray-500 mb-3">
        可选。用于访问 arXiv、MinerU 云端与模型服务（从 Finder 启动的应用不会继承终端里的代理环境变量）。
      </p>
      <input
        v-model.trim="settings.proxy_url"
        class="w-full px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm font-mono focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
        placeholder="http://127.0.0.1:7890 或 socks5://127.0.0.1:7890"
      />
    </section>
  </div>
</template>
