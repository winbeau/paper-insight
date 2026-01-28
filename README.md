<h1><img src="frontend/public/logo.svg" alt="PaperInsight logo" width="32" height="32" /> PaperInsight</h1>

> AI-powered arXiv paper tracker with cross-domain insight analysis for your research.

![Vue.js](https://img.shields.io/badge/Vue.js-3.x-4FC08D?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-3-003B57?logo=sqlite&logoColor=white)
![Dify](https://img.shields.io/badge/Dify-Workflow-blue)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

[English](README.md) | [中文](README_zh.md)

## Overview

PaperInsight automatically fetches papers from arXiv, analyzes their relevance to your research focus using Dify Workflow (with DeepSeek R1 reasoning), and presents them in a clean, modern dashboard with AI-generated cross-domain insights.

### Key Features

- **Automated Paper Fetching** — Daily retrieval from arXiv based on configurable research topics (06:00 UTC)
- **AI-Powered Analysis** — Dify Workflow generates paper essence, concept bridging, relevance scores, and heuristic suggestions
- **Real-time Streaming** — SSE-based streaming for LLM analysis with live thinking process display
- **Smart Filtering** — Filter papers by relevance score (High/Low) and processing status
- **Modern Dashboard** — Clean, academic-yet-modern UI inspired by Linear and Vercel's design language
- **PDF Thumbnails** — Auto-generated first-page thumbnails for visual paper identification
- **Batch Processing** — Process multiple papers concurrently with progress tracking
- **arXiv Import** — Manually import any paper by arXiv URL or ID
- **Structured Logging** — Full-stack logging system for debugging and monitoring

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vue 3, TypeScript, Vite, Tailwind CSS |
| Backend | FastAPI, SQLModel, SQLite |
| AI | Dify Workflow API (DeepSeek R1) |
| Data Source | arXiv API |
| Scheduling | APScheduler |

## Quick Start

### Prerequisites

- Python 3.12+ with [uv](https://github.com/astral-sh/uv)
- Node.js 18+ & pnpm
- Dify API Key (self-hosted or cloud)

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/paper-insight.git
cd paper-insight
```

### 2. Backend Setup

```bash
cd backend

# Install dependencies with uv
uv sync

# Configure environment
cp .env.example .env
# Edit .env and add your DIFY_API_KEY

# Run the server (SQLite database auto-created)
uv run uvicorn app.main:app --reload
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
pnpm install

# Run development server
pnpm dev
```

### 4. Access the Dashboard

Open [http://localhost:5173](http://localhost:5173) in your browser.

## Configuration

### Environment Variables

Create a `.env` file in the `backend/` directory:

```env
# Database (SQLite - auto-created)
DATABASE_URL=sqlite:///paper_insight.db

# Dify Workflow API
DIFY_API_KEY=app-xxxxxxxxxxxxxxxx
DIFY_API_BASE=http://your-dify-instance:8080/v1
```

### Research Settings (In-App)

Use the in-app **Settings** modal to configure:

- **arXiv Categories**: Select categories to scope the search (cs.CV, cs.LG, cs.CL, etc.)
- **Research Keywords**: arXiv query string with AND/OR logic
- **Research Idea**: Your research context for cross-domain insight analysis (sent to Dify)
- **System Prompt**: Advanced prompt customization

### Scoring & Visibility

| Score | Label | Behavior |
|-------|-------|----------|
| 9–10 | High | Shown prominently |
| 5–8 | Low | Shown in feed |
| < 5 | Skipped | Hidden from default listing |

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/constants` | Get arXiv category options |
| `GET` | `/stats` | Get statistics |
| `GET` | `/settings` | Get app settings |
| `PUT` | `/settings` | Update app settings |
| `GET` | `/papers` | List papers with filters |
| `GET` | `/papers/pending` | Get pending paper IDs |
| `GET` | `/papers/{id}` | Get paper by ID |
| `DELETE` | `/papers/{id}` | Delete paper |
| `POST` | `/papers/import` | Import paper from arXiv URL |
| `POST` | `/papers/fetch` | Trigger paper fetching |
| `GET` | `/papers/fetch/stream` | Stream fetch progress (SSE) |
| `POST` | `/papers/process/batch` | Batch process papers |
| `GET` | `/papers/process/batch/stream` | Stream batch progress (SSE) |
| `POST` | `/papers/{id}/process` | Process single paper |
| `GET` | `/papers/{id}/process/stream` | Stream processing (SSE) |

### Query Parameters

```
GET /papers?skip=0&limit=20&min_score=7&processed_only=true
```

## Project Structure

```
paper-insight/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry
│   │   ├── models.py            # SQLModel schemas
│   │   ├── database.py          # Database connection
│   │   ├── constants.py         # arXiv categories
│   │   ├── dependencies.py      # DI providers
│   │   ├── logging_config.py    # Logging setup
│   │   ├── middleware.py        # Request logging
│   │   ├── api/                 # Route modules
│   │   │   ├── health.py
│   │   │   ├── settings.py
│   │   │   ├── papers.py
│   │   │   ├── processing.py
│   │   │   └── stats.py
│   │   ├── services/
│   │   │   ├── arxiv_bot.py     # arXiv fetcher
│   │   │   ├── dify_client.py   # Dify API client
│   │   │   └── pdf_renderer.py  # Thumbnail generator
│   │   └── static/thumbnails/   # Generated thumbnails
│   ├── .env.example
│   └── pyproject.toml
│
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── layout/          # AppSidebar
    │   │   ├── paper/           # PaperCard, ThumbnailPreview
    │   │   └── ui/              # RelevanceBadge, AnalysisBox, ThinkingPanel
    │   ├── composables/         # Vue composables
    │   ├── services/api.ts      # API client with interceptors
    │   ├── utils/logger.ts      # Frontend logger
    │   ├── types/               # TypeScript types
    │   ├── App.vue
    │   └── style.css            # Design system
    ├── package.json
    └── vite.config.ts
```

## Logging

PaperInsight includes a comprehensive logging system:

### Backend
- **Format**: `YYYY-MM-DD HH:mm:ss | LEVEL | module | message`
- **Request logging**: All HTTP requests with timing
- **Service logging**: arXiv fetching, Dify analysis, PDF rendering

### Frontend
- **Development**: All log levels (debug, info, warn, error)
- **Production**: warn and error only
- **Axios interceptors**: Request/response logging

## Roadmap

- [x] Scheduled automatic fetching (APScheduler)
- [x] Real-time streaming with SSE
- [x] PDF thumbnail generation
- [x] Batch processing with concurrency control
- [x] Structured logging system
- [ ] Full-text search across papers
- [ ] Export to Notion/Obsidian
- [ ] Paper collections/bookmarks
- [ ] Email digest notifications

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [arXiv](https://arxiv.org/) for providing open access to research papers
- [Dify](https://dify.ai/) for the powerful workflow orchestration platform
- [DeepSeek](https://deepseek.com/) for the R1 reasoning model
- Design inspiration from [Linear](https://linear.app/) and [Vercel](https://vercel.com/)
