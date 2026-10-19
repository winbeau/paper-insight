<script setup lang="ts">
import { ref } from 'vue'

const RELEASES_URL = 'https://github.com/winbeau/paper-insight/releases/latest'
const REPO_URL = 'https://github.com/winbeau/paper-insight'
const open = ref(true)
</script>

<template>
  <div
    v-if="open"
    class="fixed bottom-5 right-5 z-40 w-[340px] rounded-xl border border-[var(--color-paper-200)] bg-white/95 backdrop-blur shadow-[var(--shadow-card-hover)] p-4 animate-slide-up"
  >
    <div class="flex items-start gap-3">
      <div class="flex-1 min-w-0">
        <p class="text-sm font-semibold text-[var(--color-ink-900)]">在线演示</p>
        <p class="mt-1 text-xs leading-relaxed text-[var(--color-ink-700)]">
          论文、AI 分析与「Fill with AI」均来自一次真实运行（DeepSeek-V4.1-Flash + 本地 MinerU），点击 analyze 会回放真实的分析过程。修改只保存在本页面。
        </p>
        <div class="mt-3 flex items-center gap-2">
          <a
            :href="RELEASES_URL"
            target="_blank"
            rel="noopener"
            class="px-3 py-1.5 text-xs font-medium text-white bg-[var(--color-ink-900)] rounded-lg hover:bg-[var(--color-ink-700)]"
          >
            下载 macOS 版
          </a>
          <a :href="REPO_URL" target="_blank" rel="noopener" class="px-3 py-1.5 text-xs text-[var(--color-ink-700)] hover:underline">
            GitHub
          </a>
        </div>
      </div>
      <button class="p-1 -m-1 rounded text-[var(--color-ink-400)] hover:text-[var(--color-ink-900)]" title="关闭" @click="open = false">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  </div>
</template>
