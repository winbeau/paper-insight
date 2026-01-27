<script setup lang="ts">
import { ref, computed } from 'vue'
import MarkdownRenderer from './MarkdownRenderer.vue'

const props = defineProps<{
  paperEssence: string | null
  conceptBridging: string | null
  relevanceReason: string | null
}>()

const isExpanded = ref(false)

const hasContent = computed(() => {
  return props.paperEssence || props.conceptBridging || props.relevanceReason
})

// Check if content needs expansion
const needsExpansion = computed(() => {
  const totalLength =
    (props.paperEssence?.length || 0) +
    (props.conceptBridging?.length || 0) +
    (props.relevanceReason?.length || 0)
  return totalLength > 500
})
</script>

<template>
  <div
    v-if="hasContent"
    class="analysis-box group"
    :class="{ 'cursor-pointer': needsExpansion }"
    @click.stop="needsExpansion && (isExpanded = !isExpanded)"
  >
    <!-- Decorative gradient bar -->
    <div class="absolute top-0 left-0 right-0 h-1 rounded-t-xl opacity-80" style="background: linear-gradient(to right, #fbbf24, #f97316, #fbbf24);" />

    <!-- Glow effect on hover -->
    <div class="glow-effect" />

    <div class="relative p-5">
      <!-- Header -->
      <div class="flex items-center gap-3 mb-4">
        <div class="icon-container">
          <svg
            class="w-5 h-5 text-white"
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
        <div>
          <h3 class="text-sm font-semibold text-[var(--color-ink-800)] tracking-tight">
            Heuristic Insight
          </h3>
          <p class="text-xs text-[var(--color-ink-400)]">
            AI-generated cross-domain insight
          </p>
        </div>
      </div>

      <!-- Content sections -->
      <div
        class="content-container space-y-4"
        :class="{ 'collapsed': needsExpansion && !isExpanded }"
      >
        <!-- Paper Essence -->
        <div v-if="paperEssence" class="section">
          <div class="section-header">
            <span class="section-icon">📄</span>
            <span class="section-title">论文精华</span>
          </div>
          <MarkdownRenderer
            :content="paperEssence"
            class="section-content"
          />
        </div>

        <!-- Concept Bridging -->
        <div v-if="conceptBridging" class="section">
          <div class="section-header">
            <span class="section-icon">🔗</span>
            <span class="section-title">概念桥接</span>
          </div>
          <MarkdownRenderer
            :content="conceptBridging"
            class="section-content"
          />
        </div>

        <!-- Relevance Reason -->
        <div v-if="relevanceReason" class="section">
          <div class="section-header">
            <span class="section-icon">🎯</span>
            <span class="section-title">相关性分析</span>
          </div>
          <MarkdownRenderer
            :content="relevanceReason"
            class="section-content"
          />
        </div>

        <!-- Fade overlay when collapsed -->
        <div
          v-if="needsExpansion && !isExpanded"
          class="fade-overlay"
        />
      </div>

      <!-- Expand/Collapse button -->
      <button
        v-if="needsExpansion"
        @click.stop="isExpanded = !isExpanded"
        class="expand-button"
      >
        <span>{{ isExpanded ? 'Collapse' : 'Show more' }}</span>
        <svg
          class="w-3.5 h-3.5 transition-transform duration-200"
          :class="{ 'rotate-180': isExpanded }"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.analysis-box {
  position: relative;
  background: linear-gradient(to bottom right, var(--color-paper-100), rgba(255, 251, 235, 0.3));
  border-radius: 0.75rem;
  border: 1px solid rgba(251, 191, 36, 0.3);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  transition: all 0.3s ease;
}

.analysis-box:hover {
  box-shadow: 0 4px 6px rgba(245, 158, 11, 0.1);
  border-color: rgba(251, 191, 36, 0.5);
}

.glow-effect {
  position: absolute;
  inset: 0;
  border-radius: 0.75rem;
  background: linear-gradient(to bottom right, rgba(245, 158, 11, 0.05), rgba(249, 115, 22, 0.05));
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.analysis-box:hover .glow-effect {
  opacity: 1;
}

.icon-container {
  flex-shrink: 0;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.75rem;
  background: linear-gradient(to bottom right, #fbbf24, #f97316);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 6px rgba(245, 158, 11, 0.2);
}

.content-container {
  position: relative;
  overflow: hidden;
  transition: all 0.3s ease;
}

.content-container.collapsed {
  max-height: 280px;
}

.section {
  padding: 0.75rem;
  background: rgba(255, 255, 255, 0.5);
  border-radius: 0.5rem;
  border: 1px solid rgba(251, 191, 36, 0.15);
}

.section-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}

.section-icon {
  font-size: 0.875rem;
}

.section-title {
  font-size: 0.75rem;
  font-weight: 600;
  color: #92400e;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.section-content {
  font-size: 0.875rem;
  line-height: 1.6;
  color: var(--color-ink-700);
}

.fade-overlay {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 4rem;
  background: linear-gradient(to top, var(--color-paper-100), transparent);
  pointer-events: none;
}

.expand-button {
  margin-top: 0.75rem;
  display: flex;
  align-items: center;
  gap: 0.375rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: #d97706;
  transition: color 0.15s ease;
}

.expand-button:hover {
  color: #b45309;
}

/* Markdown content styling */
:deep(.section-content p) {
  margin: 0;
}

:deep(.section-content ul),
:deep(.section-content ol) {
  margin: 0.5rem 0;
  padding-left: 1.25rem;
}

:deep(.section-content li) {
  margin: 0.25rem 0;
}

:deep(.section-content strong) {
  color: #92400e;
}
</style>
