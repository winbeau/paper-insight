<script setup lang="ts">
import type { AppSettings } from '../../types/paper'
import ModelPicker from './ModelPicker.vue'
import MineruLocalPanel from './MineruLocalPanel.vue'

const settings = defineModel<AppSettings>('settings', { required: true })

const inputClass =
  'px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none'
const labelClass = 'text-[11px] font-medium text-gray-500 uppercase tracking-wider'
</script>

<template>
  <div class="space-y-8">
    <!-- Flow overview -->
    <div class="flex items-center gap-1.5 text-[11px] text-gray-500 flex-wrap">
      <span class="px-2 py-0.5 rounded bg-gray-100">下载 PDF</span><span>→</span>
      <span class="px-2 py-0.5 rounded bg-blue-50 text-blue-700">① 解析 PDF · MinerU</span><span>→</span>
      <span class="px-2 py-0.5 rounded bg-purple-50 text-purple-700">② 图像识别 · 视觉模型</span><span>→</span>
      <span class="px-2 py-0.5 rounded bg-amber-50 text-amber-700">③ 推理分析 · 推理模型</span><span>→</span>
      <span class="px-2 py-0.5 rounded bg-gray-100">整合输出</span>
    </div>

    <!-- 1. Parser -->
    <section class="space-y-3">
      <div>
        <h3 class="text-sm font-semibold text-[var(--color-ink-900)]">① PDF 解析 / OCR（MinerU）</h3>
        <p class="text-xs text-gray-500 mt-0.5">将论文 PDF 转为 Markdown 并提取图表。解析失败时该论文标记为失败，可稍后重试。</p>
      </div>
      <div class="grid grid-cols-2 gap-3">
        <label
          v-for="engine in [
            { value: 'mineru_cloud', title: 'MinerU 云端', desc: 'mineru.net 精准解析 API，需要 Token' },
            { value: 'mineru_local', title: 'MinerU 本地', desc: '在本机运行，模型检查点下载到本地' },
          ]"
          :key="engine.value"
          class="flex items-start gap-2 p-3 rounded-lg border cursor-pointer transition-colors"
          :class="settings.pipeline.parser.engine === engine.value ? 'border-blue-500 bg-blue-50/50 ring-1 ring-blue-500' : 'border-gray-200 hover:bg-gray-50'"
        >
          <input v-model="settings.pipeline.parser.engine" type="radio" :value="engine.value" class="mt-0.5" />
          <span>
            <span class="block text-sm font-medium text-gray-900">{{ engine.title }}</span>
            <span class="block text-xs text-gray-500">{{ engine.desc }}</span>
          </span>
        </label>
      </div>

      <!-- Cloud -->
      <div v-if="settings.pipeline.parser.engine === 'mineru_cloud'" class="space-y-3">
        <label class="block">
          <span :class="labelClass">API Token</span>
          <input
            v-model.trim="settings.pipeline.parser.cloud.token"
            type="password"
            autocomplete="off"
            :class="[inputClass, 'mt-1 w-full font-mono']"
            placeholder="在 mineru.net → API 管理 中创建"
          />
        </label>
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span :class="labelClass">模型版本</span>
            <select v-model="settings.pipeline.parser.cloud.model_version" :class="[inputClass, 'mt-1 w-full']">
              <option value="vlm">vlm（推荐，精度高）</option>
              <option value="pipeline">pipeline（更快）</option>
            </select>
          </label>
          <label class="block">
            <span :class="labelClass">文档语言</span>
            <select v-model="settings.pipeline.parser.cloud.language" :class="[inputClass, 'mt-1 w-full']">
              <option value="en">en（英文）</option>
              <option value="ch">ch（中英混合）</option>
            </select>
          </label>
        </div>
        <div class="flex flex-wrap gap-4 text-xs text-gray-600">
          <label class="flex items-center gap-1.5"><input v-model="settings.pipeline.parser.cloud.is_ocr" type="checkbox" /> 强制 OCR（扫描版 PDF）</label>
          <label class="flex items-center gap-1.5"><input v-model="settings.pipeline.parser.cloud.enable_formula" type="checkbox" /> 公式识别</label>
          <label class="flex items-center gap-1.5"><input v-model="settings.pipeline.parser.cloud.enable_table" type="checkbox" /> 表格识别</label>
        </div>
      </div>

      <!-- Local -->
      <div v-else class="space-y-3">
        <div class="flex gap-4 text-xs text-gray-700">
          <label class="flex items-center gap-1.5"><input v-model="settings.pipeline.parser.local.mode" type="radio" value="managed" /> 由应用管理（自动安装与启动）</label>
          <label class="flex items-center gap-1.5"><input v-model="settings.pipeline.parser.local.mode" type="radio" value="external" /> 连接已运行的 MinerU 服务</label>
        </div>
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span :class="labelClass">Tier（模型档位）</span>
            <select v-model="settings.pipeline.parser.local.tier" :class="[inputClass, 'mt-1 w-full']">
              <option value="standard">standard（复杂版面，含 VLM）</option>
              <option value="basic">basic（OCR / 公式 / 表格，小模型）</option>
            </select>
          </label>
          <label v-if="settings.pipeline.parser.local.mode === 'managed'" class="block">
            <span :class="labelClass">模型下载源</span>
            <select v-model="settings.pipeline.parser.local.source" :class="[inputClass, 'mt-1 w-full']">
              <option value="huggingface">Hugging Face</option>
              <option value="modelscope">ModelScope（国内更快）</option>
            </select>
          </label>
        </div>
        <MineruLocalPanel v-if="settings.pipeline.parser.local.mode === 'managed'" :config="settings.pipeline.parser.local" />
        <div v-else class="grid grid-cols-2 gap-3">
          <label class="block">
            <span :class="labelClass">服务地址</span>
            <input v-model.trim="settings.pipeline.parser.local.external_url" :class="[inputClass, 'mt-1 w-full font-mono']" placeholder="http://192.168.1.10:8000" />
          </label>
          <label class="block">
            <span :class="labelClass">API Key（可选）</span>
            <input v-model.trim="settings.pipeline.parser.local.external_api_key" type="password" :class="[inputClass, 'mt-1 w-full font-mono']" placeholder="mineru-kit api-server --api-key" />
          </label>
        </div>
      </div>
    </section>

    <!-- 2. Vision -->
    <section class="space-y-3">
      <div class="flex items-start justify-between">
        <div>
          <h3 class="text-sm font-semibold text-[var(--color-ink-900)]">② 图像识别（视觉模型）</h3>
          <p class="text-xs text-gray-500 mt-0.5">逐张解读 MinerU 提取的图表，生成带编号的「视觉证据」供推理模型引用。</p>
        </div>
        <label class="flex items-center gap-1.5 text-xs text-gray-700">
          <input v-model="settings.pipeline.vision.enabled" type="checkbox" /> 启用
        </label>
      </div>
      <template v-if="settings.pipeline.vision.enabled">
        <ModelPicker
          v-model="settings.pipeline.vision"
          :providers="settings.providers"
          kind="vision"
          placeholder="支持图片输入的模型，例如 deepseek-flash / Qwen-VL 系列"
        />
        <div class="grid grid-cols-2 gap-3">
          <label class="block">
            <span :class="labelClass">每篇最多识别图表数</span>
            <input v-model.number="settings.pipeline.vision.max_figures" type="number" min="1" max="20" :class="[inputClass, 'mt-1 w-full']" />
          </label>
          <label class="block">
            <span :class="labelClass">并发请求数</span>
            <input v-model.number="settings.pipeline.vision.concurrency" type="number" min="1" max="8" :class="[inputClass, 'mt-1 w-full']" />
          </label>
        </div>
      </template>
    </section>

    <!-- 3. Reasoning -->
    <section class="space-y-3">
      <div>
        <h3 class="text-sm font-semibold text-[var(--color-ink-900)]">③ 推理分析（推理模型）<span class="text-red-500">*</span></h3>
        <p class="text-xs text-gray-500 mt-0.5">结合研究 Idea、论文全文与视觉证据输出结构化分析和相关性评分。推理内容会实时显示在卡片上。</p>
      </div>
      <ModelPicker
        v-model="settings.pipeline.reasoning"
        :providers="settings.providers"
        kind="chat"
        placeholder="例如 deepseek-flash（DeepSeek-V4.1-Flash）"
      />
      <div class="grid grid-cols-3 gap-3">
        <label class="block">
          <span :class="labelClass">Temperature</span>
          <input v-model.number="settings.pipeline.reasoning.temperature" type="number" min="0" max="2" step="0.1" :class="[inputClass, 'mt-1 w-full']" />
        </label>
        <label class="block">
          <span :class="labelClass">最大输出 tokens</span>
          <input v-model.number="settings.pipeline.reasoning.max_tokens" type="number" min="256" step="1024" :class="[inputClass, 'mt-1 w-full']" />
        </label>
        <label class="block">
          <span :class="labelClass">正文最大字符数</span>
          <input v-model.number="settings.pipeline.reasoning.max_input_chars" type="number" min="4000" step="1000" :class="[inputClass, 'mt-1 w-full']" />
        </label>
      </div>
    </section>
  </div>
</template>
