<script setup lang="ts">
import type { DirectionSummary } from '../../types/paper'

defineProps<{
  directions: DirectionSummary[]
  activeId: number | null
  busyIds: Set<number>  // directions with analyses running or queued
}>()

const emit = defineEmits<{
  select: [id: number]
  add: []
}>()
</script>

<template>
  <nav class="flex items-center gap-1.5 overflow-x-auto pb-0.5 -mb-0.5" aria-label="Research directions">
    <button
      v-for="direction in directions"
      :key="direction.id"
      class="group flex-shrink-0 flex items-center gap-2 pl-3 pr-2 py-1.5 rounded-lg text-sm font-medium border transition-colors"
      :class="direction.id === activeId
        ? 'bg-[var(--color-ink-900)] text-white border-[var(--color-ink-900)] shadow-sm'
        : 'bg-[var(--color-paper-100)] text-[var(--color-ink-700)] border-[var(--color-paper-200)] hover:border-[var(--color-paper-300)] hover:bg-[var(--color-paper-50)]'"
      :title="direction.focus_keywords.join(' · ')"
      @click="emit('select', direction.id)"
    >
      <span
        v-if="busyIds.has(direction.id) || direction.processing > 0"
        class="relative flex h-2 w-2"
        title="分析中"
      >
        <span class="absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75 animate-ping"></span>
        <span class="relative inline-flex h-2 w-2 rounded-full bg-amber-500"></span>
      </span>
      <span class="max-w-[180px] truncate">{{ direction.name }}</span>
      <span
        class="min-w-[1.5rem] px-1.5 py-0.5 rounded-md text-[11px] font-mono leading-none text-center"
        :class="direction.id === activeId
          ? 'bg-white/15 text-white'
          : 'bg-[var(--color-paper-200)] text-[var(--color-ink-400)]'"
      >
        {{ direction.total }}
      </span>
    </button>
    <button
      class="flex-shrink-0 w-8 h-8 flex items-center justify-center rounded-lg border border-dashed border-[var(--color-paper-300)] text-[var(--color-ink-400)] hover:text-[var(--color-ink-900)] hover:border-[var(--color-ink-400)] transition-colors"
      title="添加研究方向"
      @click="emit('add')"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 5v14m-7-7h14" />
      </svg>
    </button>
  </nav>
</template>
