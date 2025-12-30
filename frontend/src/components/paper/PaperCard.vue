<script setup lang="ts">
import { ref, computed, reactive, nextTick } from 'vue'
import type { Paper } from '../../types/paper'
import RelevanceBadge from '../ui/RelevanceBadge.vue'
import HeuristicBox from '../ui/HeuristicBox.vue'

const props = defineProps<{
  paper: Paper
}>()

const isExpanded = ref(false)
const isHoveringAbstract = ref(false)
const abstractRef = ref<HTMLElement | null>(null)
const thumbnailStyle = ref({
  left: '0px',
  top: '0px',
})
const previewOrigin = ref('origin-left')

const formattedDate = computed(() => {
  const date = new Date(props.paper.published)
  const now = new Date()
  const diffDays = Math.floor((now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24))

  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays} days ago`

  return date.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined,
  })
})

const authorsList = computed(() => {
  const authors = props.paper.authors.split(',').map(a => a.trim())
  if (authors.length <= 2) return authors.join(', ')
  return `${authors[0]} et al.`
})

const categoriesList = computed(() => {
  return props.paper.categories.split(',').map(c => c.trim()).slice(0, 3)
})

function toggleExpand() {
  isExpanded.value = !isExpanded.value
}

function handleMouseEnter() {
  if (!abstractRef.value || !props.paper.thumbnail_url) return

  const abstractRect = abstractRef.value.getBoundingClientRect()
  const thumbWidth = 400 // Matches w-[400px]
  const thumbHeight = 500 // Estimate
  const padding = 16 

  let newLeft = abstractRect.right + padding
  let newTop = abstractRect.top
  let origin = 'origin-left'

  // Check right edge
  if (newLeft + thumbWidth > window.innerWidth) {
    newLeft = abstractRect.left - thumbWidth - padding
    // If we moved it to the left, change origin to right so it grows from the text
    origin = 'origin-right'
    
    // Constrain to left edge if it would go off left
    if (newLeft < padding) {
      newLeft = padding
      origin = 'origin-left' // Fallback if forced to left edge? Maybe center? Keep simple.
    }
  }
  
  // Check bottom edge
  if (newTop + thumbHeight > window.innerHeight) {
    newTop = window.innerHeight - thumbHeight - padding
    if (newTop < padding) {
      newTop = padding
    }
  }
  
  // Ensure it doesn't go off screen to the top
  newTop = Math.max(padding, newTop);

  thumbnailStyle.value = {
    left: `${newLeft}px`,
    top: `${newTop}px`
  }
  previewOrigin.value = origin
  isHoveringAbstract.value = true
}

function handleMouseLeave() {
  isHoveringAbstract.value = false
}
</script>

<template>
  <article
    class="bg-[var(--color-paper-100)] rounded-xl border border-[var(--color-paper-200)] transition-all duration-200 cursor-pointer"
    :class="[
      isExpanded
        ? 'shadow-[var(--shadow-card-hover)]'
        : 'shadow-[var(--shadow-card)] hover:shadow-[var(--shadow-card-hover)] hover:-translate-y-0.5'
    ]"
    @click="toggleExpand"
  >
    <div class="p-5">
      <!-- Header -->
      <div class="flex items-start gap-3 mb-3">
        <RelevanceBadge :score="paper.relevance_score" />
        <h2 class="font-display text-lg font-semibold text-[var(--color-ink-900)] leading-snug flex-1">
          {{ paper.title }}
        </h2>
        <button
          v-if="isExpanded"
          @click.stop="isExpanded = false"
          class="flex-shrink-0 p-1 rounded-lg hover:bg-[var(--color-paper-200)] text-[var(--color-ink-400)] transition-colors"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Heuristic Idea (Focal Point) -->
      <HeuristicBox :content="paper.heuristic_idea" class="mb-4" />

      <!-- Expanded Content -->
      <Transition name="card-expand">
        <div v-if="isExpanded" class="space-y-4 mb-4 animate-fade-in">
          <!-- Chinese Summary -->
          <div v-if="paper.summary_zh">
            <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-2">
              Summary (中文)
            </h3>
            <p class="text-[var(--color-ink-700)] text-sm leading-relaxed">
              {{ paper.summary_zh }}
            </p>
          </div>

          <!-- Abstract -->
          <div>
            <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-2">
              Abstract
            </h3>
            <div
              ref="abstractRef"
              class="relative group"
              @mouseenter="handleMouseEnter"
              @mouseleave="handleMouseLeave"
            >
              <p class="text-[var(--color-ink-700)] text-sm leading-relaxed cursor-help">
                {{ paper.abstract }}
              </p>

              <Teleport to="body">
                <Transition
                  :enter-active-class="`transition duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] transform ${previewOrigin}`"
                  enter-from-class="opacity-0 scale-90 translate-y-2 translate-x-[-10px]"
                  enter-to-class="opacity-100 scale-100 translate-y-0 translate-x-0"
                  :leave-active-class="`transition duration-200 ease-in transform ${previewOrigin}`"
                  leave-from-class="opacity-100 scale-100 translate-y-0"
                  leave-to-class="opacity-0 scale-95 translate-y-2"
                >
                  <div 
                    v-if="isHoveringAbstract && paper.thumbnail_url"
                    class="fixed z-[9999] pointer-events-none shadow-2xl rounded-lg border-2 border-white bg-white w-[400px] ring-1 ring-black/5 flex flex-col"
                    :style="thumbnailStyle"
                  >
                    <div class="w-full relative bg-gray-50 rounded-t-lg overflow-hidden">
                      <img 
                        :src="paper.thumbnail_url" 
                        class="w-full h-auto object-contain block"
                        alt="Paper Preview"
                      />
                      <!-- Gradient overlay for depth -->
                      <div class="absolute inset-0 bg-gradient-to-t from-black/5 to-transparent pointer-events-none mix-blend-multiply"></div>
                    </div>
                    
                    <div class="bg-white px-3 py-2 flex items-center justify-between border-t border-gray-100 rounded-b-lg">
                      <span class="text-[10px] font-bold text-gray-400 uppercase tracking-wider">First Page Preview</span>
                      <span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
                    </div>
                  </div>
                </Transition>
              </Teleport>
            </div>
          </div>

          <!-- Relevance Reason -->
          <div v-if="paper.relevance_reason">
            <h3 class="text-xs font-semibold uppercase tracking-wider text-[var(--color-ink-400)] mb-2">
              Relevance Analysis
            </h3>
            <p class="text-[var(--color-ink-700)] text-sm leading-relaxed">
              {{ paper.relevance_reason }}
            </p>
          </div>
        </div>
      </Transition>

      <!-- Footer Meta -->
      <div class="flex items-center justify-between pt-3 border-t border-[var(--color-paper-200)]">
        <div class="flex items-center gap-2 text-sm text-[var(--color-ink-400)]">
          <span>{{ authorsList }}</span>
          <span class="text-[var(--color-paper-300)]">•</span>
          <div class="flex gap-1">
            <span
              v-for="cat in categoriesList"
              :key="cat"
              class="px-1.5 py-0.5 bg-[var(--color-paper-200)] rounded text-xs"
            >
              {{ cat }}
            </span>
          </div>
          <span class="text-[var(--color-paper-300)]">•</span>
          <span>{{ formattedDate }}</span>
        </div>

        <a
          v-if="isExpanded"
          :href="paper.pdf_url"
          target="_blank"
          rel="noopener noreferrer"
          @click.stop
          class="flex items-center gap-1.5 px-3 py-1.5 bg-[var(--color-ink-900)] text-white text-sm font-medium rounded-lg hover:bg-[var(--color-ink-700)] transition-colors"
        >
          View PDF
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
          </svg>
        </a>
      </div>
    </div>

    <!-- Processing Status -->
    <div
      v-if="!paper.is_processed"
      class="px-5 py-2 bg-[var(--color-paper-200)] rounded-b-xl border-t border-[var(--color-paper-300)]"
    >
      <span class="text-xs text-[var(--color-ink-400)] flex items-center gap-2">
        <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        Pending AI analysis...
      </span>
    </div>
  </article>
</template>
