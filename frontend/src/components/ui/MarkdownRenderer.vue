<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import type Token from 'markdown-it/lib/token.mjs'
import hljs from 'highlight.js'
import katex from 'katex'
import 'highlight.js/styles/github-dark.css'
import 'katex/dist/katex.min.css'

const props = withDefaults(defineProps<{
  content: string | null
  animate?: boolean
}>(), {
  animate: false,
})

// Initialize markdown-it with syntax highlighting
const md: MarkdownIt = new MarkdownIt({
  html: false,
  breaks: true,
  linkify: true,
  typographer: true,
  highlight: (str: string, lang: string): string => {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs-container"><code class="hljs language-${lang}">${
          hljs.highlight(str, { language: lang, ignoreIllegals: true }).value
        }</code></pre>`
      } catch {
        // Fallback
      }
    }
    return `<pre class="hljs-container"><code class="hljs">${md.utils.escapeHtml(str)}</code></pre>`
  },
})

// Add KaTeX support for math expressions
// Custom rule for inline math: $...$
// eslint-disable-next-line @typescript-eslint/no-explicit-any
md.inline.ruler.after('escape', 'math_inline', (state: any, silent: boolean): boolean => {
  if (state.src[state.pos] !== '$') return false

  const start = state.pos + 1
  let end = start

  while (end < state.src.length && state.src[end] !== '$') {
    if (state.src[end] === '\\') end++
    end++
  }

  if (end >= state.src.length) return false

  if (!silent) {
    const token = state.push('math_inline', 'math', 0)
    token.content = state.src.slice(start, end)
    token.markup = '$'
  }

  state.pos = end + 1
  return true
})

// Block math: $$...$$
// eslint-disable-next-line @typescript-eslint/no-explicit-any
md.block.ruler.after('fence', 'math_block', (state: any, startLine: number, endLine: number, silent: boolean): boolean => {
  const startPos = state.bMarks[startLine] + state.tShift[startLine]
  const maxPos = state.eMarks[startLine]

  if (startPos + 2 > maxPos) return false
  if (state.src.slice(startPos, startPos + 2) !== '$$') return false

  if (silent) return true

  let nextLine = startLine
  let endFound = false

  while (nextLine < endLine) {
    nextLine++
    if (nextLine >= endLine) break

    const lineStart = state.bMarks[nextLine] + state.tShift[nextLine]
    const lineMax = state.eMarks[nextLine]

    if (state.src.slice(lineStart, lineMax).trim() === '$$') {
      endFound = true
      break
    }
  }

  if (!endFound) return false

  const token = state.push('math_block', 'math', 0)
  token.block = true
  token.content = state.src.slice(
    state.bMarks[startLine + 1],
    state.bMarks[nextLine]
  ).trim()
  token.map = [startLine, nextLine + 1]
  token.markup = '$$'

  state.line = nextLine + 1
  return true
})

// Render math tokens
md.renderer.rules.math_inline = (tokens: Token[], idx: number): string => {
  const content = tokens[idx].content
  try {
    return katex.renderToString(content, { throwOnError: false, displayMode: false })
  } catch {
    return `<span class="math-inline math-error">$${content}$</span>`
  }
}

md.renderer.rules.math_block = (tokens: Token[], idx: number): string => {
  const content = tokens[idx].content
  try {
    return `<div class="math-block">${katex.renderToString(content, { throwOnError: false, displayMode: true })}</div>`
  } catch {
    return `<div class="math-block math-error">$$${content}$$</div>`
  }
}

const renderedContent = computed(() => {
  if (!props.content) return ''
  return md.render(props.content)
})

// Animation support
const isVisible = ref(!props.animate)

watch(() => props.content, () => {
  if (props.animate) {
    isVisible.value = false
    setTimeout(() => {
      isVisible.value = true
    }, 50)
  }
}, { immediate: true })
</script>

<template>
  <div
    class="markdown-renderer"
    :class="{ 'animate-fade-in': animate && isVisible }"
    v-html="renderedContent"
  />
</template>

<style>
.markdown-renderer {
  color: var(--color-ink-700);
  font-size: 0.875rem;
  line-height: 1.625;
}

/* Headings */
.markdown-renderer h1,
.markdown-renderer h2,
.markdown-renderer h3,
.markdown-renderer h4,
.markdown-renderer h5,
.markdown-renderer h6 {
  font-weight: 600;
  color: var(--color-ink-900);
  margin-top: 1rem;
  margin-bottom: 0.5rem;
}

.markdown-renderer h1:first-child,
.markdown-renderer h2:first-child,
.markdown-renderer h3:first-child {
  margin-top: 0;
}

.markdown-renderer h1 { font-size: 1.25rem; }
.markdown-renderer h2 { font-size: 1.125rem; }
.markdown-renderer h3 { font-size: 1rem; }

/* Paragraphs */
.markdown-renderer p {
  margin-bottom: 0.75rem;
}

.markdown-renderer p:last-child {
  margin-bottom: 0;
}

/* Lists - ChatGPT style */
.markdown-renderer ul,
.markdown-renderer ol {
  margin: 0.75rem 0;
  padding-left: 0;
}

.markdown-renderer ul {
  list-style: none;
}

.markdown-renderer ul > li {
  position: relative;
  padding-left: 1.25rem;
  margin-bottom: 0.5rem;
}

.markdown-renderer ul > li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.6em;
  width: 0.375rem;
  height: 0.375rem;
  border-radius: 50%;
  background-color: var(--color-accent-insight-border, #f59e0b);
}

.markdown-renderer ol {
  list-style: none;
  counter-reset: item;
}

.markdown-renderer ol > li {
  position: relative;
  padding-left: 1.75rem;
  margin-bottom: 0.5rem;
  counter-increment: item;
}

.markdown-renderer ol > li::before {
  content: counter(item) '.';
  position: absolute;
  left: 0;
  top: 0;
  font-weight: 600;
  color: var(--color-accent-insight-border, #f59e0b);
  min-width: 1.5rem;
}

/* Nested lists */
.markdown-renderer li ul,
.markdown-renderer li ol {
  margin-top: 0.5rem;
  margin-bottom: 0;
}

.markdown-renderer li ul > li::before {
  width: 0.25rem;
  height: 0.25rem;
  background-color: var(--color-ink-400);
}

/* Blockquotes */
.markdown-renderer blockquote {
  margin: 1rem 0;
  padding-left: 1rem;
  border-left: 2px solid var(--color-accent-insight-border, #f59e0b);
  color: var(--color-ink-600);
  font-style: italic;
}

.markdown-renderer blockquote p {
  margin-bottom: 0;
}

/* Code - inline */
.markdown-renderer code:not(.hljs) {
  padding: 0.125rem 0.375rem;
  background-color: var(--color-paper-200);
  color: var(--color-ink-800);
  border-radius: 0.25rem;
  font-size: 0.85em;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
}

/* Code blocks */
.markdown-renderer .hljs-container {
  margin: 1rem 0;
  border-radius: 0.5rem;
  overflow: hidden;
  background-color: #0d1117;
  border: 1px solid var(--color-paper-300);
}

.markdown-renderer .hljs-container code {
  display: block;
  padding: 1rem;
  font-size: 0.8rem;
  line-height: 1.625;
  overflow-x: auto;
}

/* Tables */
.markdown-renderer table {
  margin: 1rem 0;
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.markdown-renderer th {
  padding: 0.5rem 0.75rem;
  background-color: var(--color-paper-200);
  font-weight: 600;
  color: var(--color-ink-800);
  border: 1px solid var(--color-paper-300);
}

.markdown-renderer td {
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--color-paper-300);
}

.markdown-renderer tr:nth-child(even) {
  background-color: var(--color-paper-100);
}

/* Horizontal rule */
.markdown-renderer hr {
  margin: 1.5rem 0;
  border: 0;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--color-paper-300), transparent);
}

/* Links */
.markdown-renderer a {
  color: var(--color-accent-insight-border, #f59e0b);
  text-decoration: underline;
  text-decoration-color: rgba(245, 158, 11, 0.3);
  text-underline-offset: 2px;
  transition: text-decoration-color 0.15s;
}

.markdown-renderer a:hover {
  text-decoration-color: var(--color-accent-insight-border, #f59e0b);
}

/* Strong/Bold */
.markdown-renderer strong {
  font-weight: 600;
  color: var(--color-ink-800);
}

/* Emphasis/Italic */
.markdown-renderer em {
  font-style: italic;
  color: var(--color-ink-600);
}

/* Math blocks */
.markdown-renderer .math-block {
  margin: 1rem 0;
  padding: 0.75rem 1rem;
  background-color: var(--color-paper-100);
  border-radius: 0.5rem;
  overflow-x: auto;
  text-align: center;
  border: 1px solid var(--color-paper-200);
}

.markdown-renderer .math-inline {
  padding: 0 0.125rem;
}

.markdown-renderer .math-error {
  color: #ef4444;
  background-color: #fef2f2;
  padding: 0.25rem;
  border-radius: 0.25rem;
}

/* KaTeX specific overrides */
.markdown-renderer .katex {
  font-size: 1.05em;
}

.markdown-renderer .katex-display {
  margin: 0;
  overflow-x: auto;
  overflow-y: hidden;
}

/* Animation */
.markdown-renderer.animate-fade-in {
  animation: fadeInContent 0.3s ease-out forwards;
}

@keyframes fadeInContent {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
