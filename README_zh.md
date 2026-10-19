<div align="right">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a>
</div>

<p align="center">
  <img src="frontend/public/logo.svg" alt="PaperInsight logo" width="160" style="margin-bottom: 6px;" />
</p>
<h1 align="center" style="margin-top: 0; margin-bottom: 6px; font-size: 2.75rem;">PaperInsight</h1>

<p align="center" style="margin-top: 0; margin-bottom: 6px;">追踪 arXiv 论文、结合你的研究 Idea 做跨领域分析的 macOS 应用。</p>

<p align="center" style="margin-top: 0;">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-000000?logo=apple&logoColor=white" alt="macOS" />
  <img src="https://img.shields.io/badge/Vue.js-3.x-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue.js" />
  <img src="https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/MinerU-4.x-blue" alt="MinerU" />
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License" />
</p>

<p align="center"><a href="https://winbeau.github.io/paper-insight/"><b>▶ 在线演示</b></a> · <a href="https://github.com/winbeau/paper-insight/releases/latest">下载 macOS 版</a></p>

## 概述

PaperInsight 每天从 arXiv 获取新论文，用 **MinerU** 解析 PDF，用**视觉模型**解读图表，再由**推理模型**评估论文与你研究 Idea 的关联 —— 全部在一个原生 macOS 窗口中完成。每个依赖模型的步骤都可单独配置，支持任意 **兼容 OpenAI 接口** 的服务。

默认使用本地 MinerU 解析 PDF（在设置中一键安装），并用 **DeepSeek-V4.1-Flash**（`deepseek-flash`，支持文本与图片）同时完成图像识别与推理分析：安装 MinerU、填入 DeepSeek API Key 即可使用。

### 分析流程

```
下载 PDF ─▶ ① 解析 / OCR（MinerU 云端 | MinerU 本地）─▶ ② 图像识别（视觉模型）─▶ ③ 推理分析（推理模型，流式输出）─▶ 整合输出
```

| 步骤 | 引擎 | 可配置项 |
|------|------|----------|
| ① 解析 / OCR | MinerU 云端（mineru.net API）或 MinerU 本地（由应用安装并运行） | 引擎、模型版本 / Tier、OCR、公式与表格识别 |
| ② 图像识别 | 任意兼容 OpenAI 接口的视觉模型 | 服务、模型、每篇最多图表数、并发 |
| ③ 推理分析 | 任意兼容 OpenAI 接口的模型，推理过程实时显示在卡片上 | 服务、模型、温度、最大输出、正文长度、提示词 |

每篇论文输出：核心创新、与你研究的概念桥接、基于图表的事实核查（"Figure 3 支持……"）、0–10 相关性评分以及可执行的实验建议。

### 功能

- **原生 Mac 应用** —— 单窗口，无需部署服务，数据只保存在本机
- **多个研究方向** —— 每个方向有独立的 arXiv 检索式、研究 Idea 与评分提示词；设置页与首页论文流一一对应地按方向分页。同一篇论文命中多个方向时按方向分别分析，PDF、MinerU 解析与图表证据共享
- **AI 填写研究方向** —— 点击设置页底部的 **✨ Fill with AI**，用大白话描述研究，推理模型自动填写分类、检索式、研究 Idea 与评分标准，并在 arXiv 上多轮实测检索式（近 7 天数量 + 样本相关率），采用实测最佳的一轮
- **解析与分析并行** —— 开始批量处理时所有论文立即进入 MinerU 解析队列；前一篇做图像识别与推理时，MinerU 已在解析下一篇。**Stop Processing** 一键停止全部分析（含后台定时任务与 MinerU），被停止的论文回到待分析
- **提示词缓存友好** —— 请求保持字节稳定的前缀（系统提示词 + 研究 Idea；同一论文的图表共享上下文；智能填写为只追加的对话），DeepSeek 大部分输入可命中缓存；每篇论文与 `/api/usage` 会显示缓存命中率
- **每日自动获取** —— 本地时间 06:00；若 Mac 当时休眠，启动后会自动补抓
- **模型可配置** —— 内置 DeepSeek、OpenAI、阿里云百炼、硅基流动、智谱、Moonshot、OpenRouter、Ollama、LM Studio 预设，也可添加任意兼容服务；可在设置中测试并列出模型
- **本地 MinerU** —— 一键安装 MinerU 并将模型检查点下载到应用数据目录；解析时自动启动服务，空闲后自动停止
- **实时进度** —— 每张卡片显示分步进度与流式推理内容
- **历史记录管理** —— 设置 → 历史记录 列出全部论文（所有方向，含低相关论文），支持按方向 / 状态 / 关键词筛选，可删除单条、所选或全部筛选结果；对应的 PDF、解析结果与缩略图一并清理（仍被其他方向使用的论文会保留），并可一键清理无用缓存
- **arXiv 导入、筛选、PDF 缩略图、结构化日志**

## 安装

构建应用（Apple Silicon，macOS 13+）：

```bash
brew install uv pnpm      # 如未安装
./scripts/build_mac.sh    # → dist/PaperInsight.app 与 dist/PaperInsight.dmg
```

打开 DMG，将 **PaperInsight** 拖入「应用程序」。构建产物为 ad-hoc 签名（未公证）：首次启动请右键应用 →「打开」。

## 配置

打开 **Settings（设置）**：

1. **模型服务** —— 已预置 DeepSeek，填入 API Key 即可。若想为不同步骤使用不同模型，可添加其他服务。
2. **解析流程**
   - **① MinerU**：填写 [mineru.net](https://mineru.net) → API 管理 中创建的 Token（云端）；或选择 **MinerU 本地** →「安装并拉取模型」。本地安装约需 3–6 GB 磁盘（建议 16 GB 内存）；如果 Hugging Face 较慢，可将模型下载源切换为 ModelScope。也可连接已运行的 `mineru-kit api-server`。
   - **② 图像识别 / ③ 推理分析**：默认 `deepseek-flash`，可用「测试」按钮验证。
3. **研究方向** —— 每个方向一个子标签（**+** 新增）：arXiv 分类、检索式、研究 Idea（推理模型据此评估论文）与可选的评分提示词。设置页底部（Cancel / Save 左侧）的 **✨ Fill with AI** 可根据大白话描述为当前方向自动填写这四项。
4. **网络代理**（可选）—— 从 Finder 启动的应用不会继承终端里的代理环境变量，如访问 arXiv / API 需要代理请在此设置。

若 MinerU 解析某篇论文失败，该论文会被标记为失败，可稍后重试。

## 数据位置

| 内容 | 位置 |
|------|------|
| 数据库（论文、设置、API Key） | `~/Library/Application Support/PaperInsight/paper_insight.db`（权限 0600） |
| PDF、MinerU 解析结果、缩略图 | `~/Library/Application Support/PaperInsight/{pdfs,parsed,thumbnails}/` |
| 本地 MinerU（环境与模型） | `~/Library/Application Support/PaperInsight/mineru/` |
| 日志 | `~/Library/Logs/PaperInsight/app.log`、`mineru.log` |

**从服务器版本迁移：** 退出应用，把旧的 `paper_insight.db` 复制到 `~/Library/Application Support/PaperInsight/`，重新启动即可，数据库结构会自动升级。缺失的缩略图会在论文下次分析时重新生成。

## 开发

```bash
# 后端（API 在 :8000，数据写入临时目录）
cd backend
uv sync
PAPER_INSIGHT_DATA_DIR=/tmp/paper-insight-dev uv run uvicorn app.main:app --reload --port 8000

# 前端（Vite 在 :5173，将 /api 代理到 :8000）
cd frontend
pnpm install
pnpm dev

# 用桌面窗口打开构建后的前端
pnpm -C frontend build
cd backend && uv run python -m app.desktop

# 测试
cd backend && uv run pytest
```

项目结构见 [README.md](README.md#project-structure)。本地 API 仅监听 `127.0.0.1`，并拒绝来自其他主机和跨站来源的请求。

## 许可证

MIT —— 详见 [LICENSE](LICENSE)。

## 致谢

- [arXiv](https://arxiv.org/) 提供开放获取的论文
- [MinerU](https://github.com/opendatalab/MinerU) 提供 PDF 解析
- [DeepSeek](https://deepseek.com/) 提供默认模型
- [pywebview](https://pywebview.flowrl.com/) 提供原生窗口
