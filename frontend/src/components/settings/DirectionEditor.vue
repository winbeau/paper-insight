<script setup lang="ts">
import type { ArxivOption, Direction } from '../../types/paper'
import { DEFAULT_PROMPT_HINT } from './presets'

const direction = defineModel<Direction>('direction', { required: true })

defineProps<{
  arxivOptions: ArxivOption[]
}>()

function toggleCategory(code: string) {
  const categories = direction.value.arxiv_categories
  const index = categories.indexOf(code)
  if (index === -1) categories.push(code)
  else categories.splice(index, 1)
}
</script>

<template>
  <div class="space-y-7">
    <!-- Name -->
    <section>
      <label class="block">
        <span class="text-sm font-semibold text-[var(--color-ink-900)]">方向名称</span>
        <input
          v-model="direction.name"
          maxlength="40"
          class="mt-2 w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none transition-all"
          placeholder="例如：视频生成加速"
        />
      </label>
    </section>

    <!-- Arxiv Categories -->
    <section>
      <h3 class="text-sm font-semibold text-[var(--color-ink-900)] mb-2 flex items-center gap-2">
        <svg class="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
        Arxiv Categories
        <span class="text-xs font-normal text-gray-400">已选 {{ direction.arxiv_categories.length }}</span>
      </h3>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="option in arxivOptions"
          :key="option.code"
          type="button"
          class="px-2.5 py-1 rounded-md border text-xs transition-colors"
          :class="direction.arxiv_categories.includes(option.code)
            ? 'border-blue-500 bg-blue-50 text-blue-700 ring-1 ring-blue-500'
            : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50'"
          :title="option.desc"
          @click="toggleCategory(option.code)"
        >
          <span class="font-mono font-medium">{{ option.code }}</span>
          <span class="ml-1 text-[11px] opacity-70">{{ option.name }}</span>
        </button>
      </div>
      <p class="mt-2 text-xs text-gray-400">Select at least one category to fetch papers from.</p>
    </section>

    <!-- Research Focus -->
    <section>
      <h3 class="text-sm font-semibold text-[var(--color-ink-900)] mb-2 flex items-center gap-2">
        <svg class="w-4 h-4 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        Research Keywords
      </h3>
      <div class="relative">
        <textarea
          v-model="direction.research_focus"
          rows="3"
          class="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm font-mono focus:ring-2 focus:ring-purple-500/20 focus:border-purple-500 outline-none transition-all placeholder-gray-400"
          placeholder="((ti:DiT OR abs:DiT) AND (ti:compression OR abs:pruning))..."
        ></textarea>
        <div class="absolute bottom-2 right-2 text-[10px] text-gray-400 bg-white px-1">
          Supports AND/OR logic
        </div>
      </div>
    </section>

    <!-- Research Idea (analysis context) -->
    <section>
      <h3 class="text-sm font-semibold text-[var(--color-ink-900)] mb-2 flex items-center gap-2">
        <svg class="w-4 h-4 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
        Research Idea (分析上下文)
      </h3>
      <textarea
        v-model="direction.research_idea"
        rows="7"
        class="w-full px-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 outline-none transition-all placeholder-gray-400"
        placeholder="**研究主题**：你正在研究什么？
**技术背景与动机**：为什么要做这个研究？有什么痛点？
**核心方法论**：你打算用什么方法解决？
**预期科学贡献**：希望达成什么效果？"
      ></textarea>
      <p class="mt-1.5 text-xs text-gray-500">推理模型会结合此上下文评估本方向论文与你研究的关联性。</p>
    </section>

    <!-- Analysis prompt override (Advanced) -->
    <section>
      <h3 class="text-sm font-semibold text-[var(--color-ink-900)] mb-2 flex items-center gap-2">
        <svg class="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.384-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
        </svg>
        Analysis Prompt (Advanced)
      </h3>
      <textarea
        v-model="direction.system_prompt"
        rows="4"
        class="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm font-mono text-gray-600 focus:ring-2 focus:ring-gray-500/20 focus:border-gray-500 outline-none transition-all placeholder-gray-400"
        :placeholder="DEFAULT_PROMPT_HINT"
      ></textarea>
      <p class="mt-1.5 text-xs text-gray-500">
        角色设定与 0–10 评分标准；留空使用内置提示词。输出格式由程序自动追加。
      </p>
    </section>
  </div>
</template>
