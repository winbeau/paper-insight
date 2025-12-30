<script setup lang="ts">
import { computed } from 'vue'
import type { AppSettings } from '../../types/paper'

const props = defineProps<{
  settings: AppSettings | null
}>()

const keywords = computed(() => {
  if (!props.settings || !props.settings.focus_keywords) return []
  return props.settings.focus_keywords
})
</script>

<template>
  <div v-if="keywords.length > 0" class="fixed bottom-6 left-6 z-40 max-w-md pointer-events-none">
    <div class="flex flex-wrap gap-2 items-center">
      <div class="flex items-center gap-2 px-3 py-1.5 rounded-full bg-white/80 backdrop-blur-md shadow-sm border border-white/40">
        <span class="relative flex h-2 w-2">
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
          <span class="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
        </span>
        <span class="text-[10px] font-bold text-gray-500 uppercase tracking-wider">Monitoring</span>
      </div>
      
      <div 
        v-for="keyword in keywords" 
        :key="keyword"
        class="px-2.5 py-1 rounded-md bg-white/60 backdrop-blur-md border border-white/40 shadow-sm text-xs font-medium text-gray-700 animate-fade-in"
      >
        {{ keyword }}
      </div>
    </div>
  </div>
</template>
