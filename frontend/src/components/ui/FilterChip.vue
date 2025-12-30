<script setup lang="ts">
defineProps<{
  label: string
  active?: boolean
  count?: number
}>()

defineEmits<{
  click: []
}>()
</script>

<template>
  <button
    @click="$emit('click')"
    :class="[
      'flex items-center justify-between w-full px-3 py-2 text-sm rounded-lg transition-all duration-150',
      active
        ? 'bg-[var(--color-ink-900)] text-white'
        : 'text-[var(--color-ink-700)] hover:bg-[var(--color-paper-200)]'
    ]"
  >
    <span>{{ label }}</span>
    <span
      v-if="count !== undefined"
      :class="[
        'text-xs font-mono px-1.5 py-0.5 rounded',
        active ? 'bg-white/20' : 'bg-[var(--color-paper-200)]'
      ]"
    >
      {{ count }}
    </span>
  </button>
</template>
