<script setup lang="ts">
import { ref, onMounted } from 'vue'
import axios from 'axios'
import type { AppSettings } from '../types/paper'

interface ArxivOption {
  code: string
  name: string
  desc: string
}

const emit = defineEmits(['close'])

const loading = ref(true)
const saving = ref(false)
const arxivOptions = ref<ArxivOption[]>([])
const settings = ref<AppSettings>({
  id: 1,
  research_focus: '',
  focus_keywords: [],
  system_prompt: '',
  arxiv_categories: [], // Default to empty, will be populated from API
})

const api = axios.create({
  baseURL: '/api', // Proxy handles this
})

onMounted(async () => {
  try {
    const [constantsRes, settingsRes] = await Promise.all([
      api.get('/constants'),
      api.get('/settings'),
    ])
    arxivOptions.value = constantsRes.data.arxiv_options
    settings.value = settingsRes.data
    // Ensure default if empty (though backend handles default on creation, explicitly empty list is valid)
    if (!settings.value.arxiv_categories) {
        settings.value.arxiv_categories = []
    }
  } catch (e) {
    console.error('Failed to load settings:', e)
  } finally {
    loading.value = false
  }
})

async function saveSettings() {
  saving.value = true
  try {
    await api.put('/settings', settings.value)
    emit('close')
  } catch (e) {
    console.error('Failed to save settings:', e)
  } finally {
    saving.value = false
  }
}

function toggleCategory(code: string) {
  const index = settings.value.arxiv_categories.indexOf(code)
  if (index === -1) {
    settings.value.arxiv_categories.push(code)
  } else {
    settings.value.arxiv_categories.splice(index, 1)
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
      <div class="relative bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col animate-slide-up">
        <!-- Header -->
        <div class="px-6 py-4 border-b border-gray-100 flex items-center justify-between bg-gray-50/50">
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

        <!-- Body -->
        <div class="p-6 overflow-y-auto flex-1 space-y-8">
          <div v-if="loading" class="flex justify-center py-12">
            <svg class="w-8 h-8 animate-spin text-gray-300" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>

          <template v-else>
            <!-- Arxiv Categories -->
            <section>
              <h3 class="text-sm font-semibold text-[var(--color-ink-900)] mb-3 flex items-center gap-2">
                <svg class="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                Arxiv Categories
              </h3>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div 
                  v-for="option in arxivOptions" 
                  :key="option.code"
                  class="relative flex items-start p-3 rounded-lg border cursor-pointer transition-all duration-200 group"
                  :class="[
                    settings.arxiv_categories.includes(option.code)
                      ? 'border-blue-500 bg-blue-50/50 ring-1 ring-blue-500'
                      : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  ]"
                  @click="toggleCategory(option.code)"
                >
                  <div class="flex items-center h-5">
                    <input
                      type="checkbox"
                      :checked="settings.arxiv_categories.includes(option.code)"
                      class="h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                      readonly
                    />
                  </div>
                  <div class="ml-3 text-sm">
                    <label class="font-medium text-gray-900 cursor-pointer block">
                      {{ option.code }}
                      <span class="font-normal text-gray-500 ml-1">- {{ option.name }}</span>
                    </label>
                    <p class="text-gray-500 text-xs mt-1 leading-snug">{{ option.desc }}</p>
                  </div>
                </div>
              </div>
              <p class="mt-2 text-xs text-gray-400">
                Select at least one category to fetch papers from.
              </p>
            </section>

            <!-- Research Focus -->
            <section>
              <h3 class="text-sm font-semibold text-[var(--color-ink-900)] mb-3 flex items-center gap-2">
                <svg class="w-4 h-4 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                Research Keywords
              </h3>
              <div class="relative">
                              <textarea
                                v-model="settings.research_focus"
                                rows="3"
                                class="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-purple-500/20 focus:border-purple-500 outline-none transition-all placeholder-gray-400"
                                placeholder="((ti:DiT OR abs:DiT) AND (ti:compression OR abs:pruning))..."
                              ></textarea>                <div class="absolute bottom-2 right-2 text-[10px] text-gray-400 bg-white px-1">
                  Supports AND/OR logic
                </div>
              </div>
            </section>

            <!-- System Prompt (Advanced) -->
            <section>
              <h3 class="text-sm font-semibold text-[var(--color-ink-900)] mb-3 flex items-center gap-2">
                <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
                </svg>
                System Prompt (Advanced)
              </h3>
              <textarea
                v-model="settings.system_prompt"
                rows="4"
                class="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm font-mono text-gray-600 focus:ring-2 focus:ring-gray-500/20 focus:border-gray-500 outline-none transition-all placeholder-gray-400"
                placeholder="You are a research assistant..."
              ></textarea>
            </section>
          </template>
        </div>

        <!-- Footer -->
        <div class="px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex justify-end gap-3">
          <button
            @click="$emit('close')"
            class="px-4 py-2 text-sm font-medium text-gray-600 hover:text-gray-900 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Cancel
          </button>
          <button
            @click="saveSettings"
            :disabled="saving"
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
