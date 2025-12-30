<script setup lang="ts">
import { ref, computed } from 'vue'
import type { Stats, FilterType, StatusFilter, AppSettings } from '../../types/paper'
import FilterChip from '../ui/FilterChip.vue'
import SettingsModal from '../SettingsModal.vue'

const props = defineProps<{
  stats: Stats | null
  settings: AppSettings | null // New settings prop
  relevanceFilter: FilterType
  statusFilter: StatusFilter
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:relevanceFilter': [value: FilterType]
  'update:statusFilter': [value: StatusFilter]
  fetch: []
  'settings-saved': [] // New emit for when settings are saved
}>()

const showSettings = ref(false)

const relevanceOptions: { value: FilterType; label: string }[] = [
  { value: 'all', label: 'All Papers' },
  { value: 'high', label: 'High Relevance (8+)' },
  { value: 'medium', label: 'Medium (5-8)' },
  { value: 'low', label: 'Low (<5)' },
]

const statusOptions: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All Status' },
  { value: 'processed', label: 'Processed' },
  { value: 'pending', label: 'Pending' },
]

const focusKeywords = computed(() => {
  if (!props.settings) return []
  if (props.settings.focus_keywords && props.settings.focus_keywords.length > 0) {
    return props.settings.focus_keywords
  }
  if (!props.settings.research_focus) return []
  return props.settings.research_focus
    .split(/[;]+/)
    .map((keyword) => keyword.trim())
    .filter(Boolean)
})

function handleSettingsClose() {
  showSettings.value = false
  emit('settings-saved')
}
</script>

<template>
  <aside class="w-64 flex-shrink-0 bg-[var(--color-paper-100)] border-r border-[var(--color-paper-200)] shadow-[var(--shadow-sidebar)] h-screen sticky top-0 flex flex-col">
    <div class="p-6 flex-1 overflow-y-auto">
      <!-- Logo / Title -->
      <div class="mb-8">
        <h1 class="font-display text-2xl font-bold text-[var(--color-ink-900)] tracking-tight">
          Paper<span class="text-[var(--color-relevance-mid)]">Insight</span>
        </h1>
        <p class="text-sm text-[var(--color-ink-400)] mt-1">
          AI Research Tracker
        </p>
      </div>

      <!-- Stats Card -->
      <div v-if="stats" class="bg-[var(--color-paper-50)] rounded-lg p-4 mb-6 border border-[var(--color-paper-200)]">
        <div class="grid grid-cols-2 gap-3 text-center">
          <div>
            <p class="text-2xl font-mono font-semibold text-[var(--color-ink-900)]">
              {{ stats.total_papers }}
            </p>
            <p class="xs text-[var(--color-ink-400)]">Total</p>
          </div>
          <div>
            <p class="text-2xl font-mono font-semibold text-[var(--color-relevance-high)]">
              {{ stats.high_relevance_papers }}
            </p>
            <p class="text-xs text-[var(--color-ink-400)]">High Relevance</p>
          </div>
        </div>
      </div>

      <!-- Fetch Button -->
      <button
        @click="emit('fetch')"
        :disabled="loading"
        class="w-full mb-6 px-4 py-2.5 bg-[var(--color-ink-900)] text-white text-sm font-medium rounded-lg hover:bg-[var(--color-ink-700)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
      >
        <svg
          class="w-4 h-4"
          :class="{ 'animate-spin': loading }"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        {{ loading ? 'Fetching...' : 'Fetch New Papers' }}
      </button>

      <!-- Relevance Filter -->
      <div class="mb-6">
        <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-3 px-1">
          Relevance
        </h3>
        <div class="space-y-1">
          <FilterChip
            v-for="opt in relevanceOptions"
            :key="opt.value"
            :label="opt.label"
            :active="relevanceFilter === opt.value"
            @click="emit('update:relevanceFilter', opt.value)"
          />
        </div>
      </div>

      <!-- Status Filter -->
      <div>
        <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-3 px-1">
          Status
        </h3>
        <div class="space-y-1">
          <FilterChip
            v-for="opt in statusOptions"
            :key="opt.value"
            :label="opt.label"
            :active="statusFilter === opt.value"
            :count="opt.value === 'pending' && stats ? stats.pending_processing : undefined"
            @click="emit('update:statusFilter', opt.value)"
          />
        </div>
      </div>

      <!-- Research Focus (Dynamic) -->
      <div class="mt-8 pt-6 border-t border-[var(--color-paper-200)]">
        <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-3 px-1">
          Research Focus
        </h3>
        <div v-if="focusKeywords.length > 0" class="px-1">
          <div class="flex flex-wrap gap-2">
            <span
              v-for="keyword in focusKeywords"
              :key="keyword"
              class="px-2.5 py-1 rounded-md bg-[var(--color-paper-50)] border border-[var(--color-paper-200)] text-xs text-[var(--color-ink-700)] font-mono shadow-sm"
            >
              {{ keyword }}
            </span>
          </div>
        </div>
        <p v-else class="px-1 text-sm text-[var(--color-ink-400)] italic">
          No focus set. Default query used.
        </p>
      </div>
    </div>

    <!-- Settings Button (Bottom) -->
    <div class="p-4 border-t border-[var(--color-paper-200)] bg-[var(--color-paper-50)]">
      <button
        @click="showSettings = true"
        class="w-full px-4 py-2 text-sm font-medium text-[var(--color-ink-700)] hover:text-[var(--color-ink-900)] bg-transparent hover:bg-[var(--color-paper-200)] rounded-lg transition-colors flex items-center justify-center gap-2"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        Settings
      </button>
    </div>

    <SettingsModal v-if="showSettings" @close="handleSettingsClose" />
  </aside>
</template>
