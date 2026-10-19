export interface ProviderPreset {
  name: string
  base_url: string
  hint: string
}

// OpenAI-compatible endpoints. Any other compatible service works via "自定义".
export const PROVIDER_PRESETS: ProviderPreset[] = [
  { name: 'DeepSeek', base_url: 'https://api.deepseek.com', hint: '推理 / 视觉（deepseek-flash）' },
  { name: 'OpenAI', base_url: 'https://api.openai.com/v1', hint: '推理 / 视觉' },
  { name: '阿里云百炼', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', hint: '推理 / 视觉（Qwen-VL 系列）' },
  { name: '硅基流动', base_url: 'https://api.siliconflow.cn/v1', hint: '推理 / 视觉（开源模型）' },
  { name: '智谱 AI', base_url: 'https://open.bigmodel.cn/api/paas/v4', hint: '推理 / 视觉（GLM-V 系列）' },
  { name: 'Moonshot', base_url: 'https://api.moonshot.cn/v1', hint: '推理' },
  { name: 'OpenRouter', base_url: 'https://openrouter.ai/api/v1', hint: '聚合多家模型' },
  { name: 'Ollama', base_url: 'http://localhost:11434/v1', hint: '本地模型，无需 API Key' },
  { name: 'LM Studio', base_url: 'http://localhost:1234/v1', hint: '本地模型，无需 API Key' },
]

export const DEFAULT_PROMPT_HINT =
  '（内置）资深 AI 研究员，跨领域技术迁移视角；结合研究 Idea、MinerU 解析的全文与视觉证据，输出 JSON 分析与 0-10 相关性评分…'

export function newProviderId(): string {
  return Math.random().toString(16).slice(2, 10)
}
