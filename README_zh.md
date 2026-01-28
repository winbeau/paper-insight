# PaperInsight

> AI 驱动的 arXiv 论文追踪器，为你的研究提供跨领域洞察分析。

![Vue.js](https://img.shields.io/badge/Vue.js-3.x-4FC08D?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![Dify](https://img.shields.io/badge/Dify-Workflow-blue)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

[English](README.md) | [中文](README_zh.md)

## 概述

PaperInsight 自动从 arXiv 获取论文，使用 Dify Workflow（集成 DeepSeek R1 推理模型）分析论文与你研究方向的关联性，并在现代化的仪表盘中展示 AI 生成的跨领域洞察。

### 核心功能

- **自动论文获取** — 基于可配置的研究主题每日从 arXiv 获取论文（UTC 06:00）
- **AI 驱动分析** — Dify Workflow 生成论文精华、概念桥接、关联度评分和启发式建议
- **实时流式传输** — 基于 SSE 的流式 LLM 分析，实时展示思考过程
- **智能过滤** — 按关联度评分（高/低）和处理状态过滤论文
- **现代化仪表盘** — 融合学术风格与现代设计语言的简洁 UI
- **PDF 缩略图** — 自动生成论文首页缩略图便于视觉识别
- **批量处理** — 支持并发处理多篇论文并追踪进度
- **arXiv 导入** — 通过 arXiv URL 或 ID 手动导入任意论文
- **结构化日志** — 全栈日志系统便于调试和监控

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3, TypeScript, Vite, Tailwind CSS |
| 后端 | FastAPI, SQLModel, SQLite |
| AI | Dify Workflow API (DeepSeek R1) |
| 数据源 | arXiv API |
| 调度 | APScheduler |

## 快速开始

### 前置条件

- Python 3.12+ 及 [uv](https://github.com/astral-sh/uv)
- Node.js 18+ 及 pnpm
- Dify API Key（自托管或云端）

### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/paper-insight.git
cd paper-insight
```

### 2. 后端配置

```bash
cd backend

# 使用 uv 安装依赖
uv sync

# 配置环境变量
cp .env.example .env
# 编辑 .env 并添加 DIFY_API_KEY

# 启动服务器（SQLite 数据库自动创建）
uv run uvicorn app.main:app --reload
```

### 3. 前端配置

```bash
cd frontend

# 安装依赖
pnpm install

# 启动开发服务器
pnpm dev
```

### 4. 访问仪表盘

在浏览器中打开 [http://localhost:5173](http://localhost:5173)。

## 配置说明

### 环境变量

在 `backend/` 目录创建 `.env` 文件：

```env
# 数据库（SQLite - 自动创建）
DATABASE_URL=sqlite:///paper_insight.db

# Dify Workflow API
DIFY_API_KEY=app-xxxxxxxxxxxxxxxx
DIFY_API_BASE=http://your-dify-instance:8080/v1
```

### 研究设置（应用内）

使用应用内的 **Settings** 弹窗配置：

- **arXiv 分类**: 选择搜索范围（cs.CV, cs.LG, cs.CL 等）
- **研究关键词**: 支持 AND/OR 逻辑的 arXiv 查询字符串
- **研究 Idea**: 你的研究背景，用于跨领域洞察分析（发送给 Dify）
- **System Prompt**: 高级提示词自定义

### 评分与可见性

| 评分 | 标签 | 行为 |
|------|------|------|
| 9–10 | 高关联 | 突出显示 |
| 5–8 | 低关联 | 正常显示 |
| < 5 | 跳过 | 默认列表中隐藏 |

## API 端点

| 方法 | 端点 | 描述 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/constants` | 获取 arXiv 分类选项 |
| `GET` | `/stats` | 获取统计数据 |
| `GET` | `/settings` | 获取应用设置 |
| `PUT` | `/settings` | 更新应用设置 |
| `GET` | `/papers` | 获取论文列表（支持过滤） |
| `GET` | `/papers/pending` | 获取待处理论文 ID |
| `GET` | `/papers/{id}` | 获取单篇论文 |
| `DELETE` | `/papers/{id}` | 删除论文 |
| `POST` | `/papers/import` | 从 arXiv URL 导入论文 |
| `POST` | `/papers/fetch` | 触发论文获取 |
| `GET` | `/papers/fetch/stream` | 获取进度流（SSE） |
| `POST` | `/papers/process/batch` | 批量处理论文 |
| `GET` | `/papers/process/batch/stream` | 批量处理进度流（SSE） |
| `POST` | `/papers/{id}/process` | 处理单篇论文 |
| `GET` | `/papers/{id}/process/stream` | 处理进度流（SSE） |

### 查询参数

```
GET /papers?skip=0&limit=20&min_score=7&processed_only=true
```

## 项目结构

```
paper-insight/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 应用入口
│   │   ├── models.py            # SQLModel 模型定义
│   │   ├── database.py          # 数据库连接
│   │   ├── constants.py         # arXiv 分类常量
│   │   ├── dependencies.py      # 依赖注入
│   │   ├── logging_config.py    # 日志配置
│   │   ├── middleware.py        # 请求日志中间件
│   │   ├── api/                 # 路由模块
│   │   │   ├── health.py
│   │   │   ├── settings.py
│   │   │   ├── papers.py
│   │   │   ├── processing.py
│   │   │   └── stats.py
│   │   ├── services/
│   │   │   ├── arxiv_bot.py     # arXiv 获取器
│   │   │   ├── dify_client.py   # Dify API 客户端
│   │   │   └── pdf_renderer.py  # 缩略图生成器
│   │   └── static/thumbnails/   # 生成的缩略图
│   ├── .env.example
│   └── pyproject.toml
│
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── layout/          # AppSidebar
    │   │   ├── paper/           # PaperCard, ThumbnailPreview
    │   │   └── ui/              # RelevanceBadge, AnalysisBox, ThinkingPanel
    │   ├── composables/         # Vue 组合式函数
    │   ├── services/api.ts      # API 客户端（含拦截器）
    │   ├── utils/logger.ts      # 前端日志工具
    │   ├── types/               # TypeScript 类型
    │   ├── App.vue
    │   └── style.css            # 设计系统
    ├── package.json
    └── vite.config.ts
```

## 日志系统

PaperInsight 包含完整的日志系统：

### 后端
- **格式**: `YYYY-MM-DD HH:mm:ss | LEVEL | module | message`
- **请求日志**: 所有 HTTP 请求及耗时
- **服务日志**: arXiv 获取、Dify 分析、PDF 渲染

### 前端
- **开发环境**: 输出所有级别（debug, info, warn, error）
- **生产环境**: 仅输出 warn 和 error
- **Axios 拦截器**: 请求/响应日志

## 路线图

- [x] 定时自动获取（APScheduler）
- [x] SSE 实时流式传输
- [x] PDF 缩略图生成
- [x] 并发控制的批量处理
- [x] 结构化日志系统
- [ ] 论文全文搜索
- [ ] 导出到 Notion/Obsidian
- [ ] 论文收藏夹
- [ ] 邮件摘要通知

## 贡献

欢迎贡献！请随时提交 Pull Request。

1. Fork 本仓库
2. 创建特性分支（`git checkout -b feature/amazing-feature`）
3. 提交更改（`git commit -m 'Add amazing feature'`）
4. 推送到分支（`git push origin feature/amazing-feature`）
5. 发起 Pull Request

## 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

## 致谢

- [arXiv](https://arxiv.org/) 提供开放获取的研究论文
- [Dify](https://dify.ai/) 强大的工作流编排平台
- [DeepSeek](https://deepseek.com/) R1 推理模型
- 设计灵感来自 [Linear](https://linear.app/) 和 [Vercel](https://vercel.com/)
