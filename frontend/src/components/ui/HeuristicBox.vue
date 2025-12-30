<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

const props = defineProps<{
  content: string | null
}>()

const md = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
})

const renderedContent = computed(() => {
  if (!props.content) return ''
  return md.render(props.content)
})
</script>

<template>
  <div
    v-if="content"
    class="relative bg-[var(--color-accent-insight)] border-l-4 border-[var(--color-accent-insight-border)] rounded-r-lg p-4 transition-all duration-200 hover:shadow-md"
  >
    <div class="flex items-start gap-3">
      <div class="flex-shrink-0 mt-0.5">
        <svg
          class="w-5 h-5 text-[var(--color-accent-insight-border)]"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"
          />
        </svg>
      </div>
      <div class="flex-1 min-w-0">
        <p class="text-xs font-medium uppercase tracking-wider text-[var(--color-accent-insight-text)] mb-1.5">
          Heuristic Insight
        </p>
        <div
          class="text-[var(--color-ink-700)] text-sm leading-relaxed markdown-content"
          v-html="renderedContent"
        />
      </div>
    </div>
  </div>
</template>
