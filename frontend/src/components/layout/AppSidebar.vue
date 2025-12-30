<script setup lang="ts">
import type { Stats, FilterType, StatusFilter } from '../../types/paper'
import FilterChip from '../ui/FilterChip.vue'

defineProps<{
  stats: Stats | null
  relevanceFilter: FilterType
  statusFilter: StatusFilter
  loading?: boolean
}>()

const emit = defineEmits<{
  'update:relevanceFilter': [value: FilterType]
  'update:statusFilter': [value: StatusFilter]
  fetch: []
}>()

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
</script>

<template>
  <aside class="w-64 flex-shrink-0 bg-[var(--color-paper-100)] border-r border-[var(--color-paper-200)] shadow-[var(--shadow-sidebar)] h-screen sticky top-0 overflow-y-auto">
    <div class="p-6">
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
            <p class="text-xs text-[var(--color-ink-400)]">Total</p>
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

      <!-- Focus Area -->
      <div class="mt-8 pt-6 border-t border-[var(--color-paper-200)]">
        <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-3 px-1">
          Research Focus
        </h3>
        <div class="space-y-2 text-sm text-[var(--color-ink-700)]">
          <div class="flex items-center gap-2 px-1">
            <span class="w-2 h-2 rounded-full bg-[var(--color-relevance-high)]"></span>
            Autoregressive DiT
          </div>
          <div class="flex items-center gap-2 px-1">
            <span class="w-2 h-2 rounded-full bg-[var(--color-relevance-mid)]"></span>
            KV Cache Compression
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>
