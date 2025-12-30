# PaperInsight

> AI-powered arXiv paper tracker focused on **Autoregressive DiT** and **KV Cache Compression** research.

![Vue.js](https://img.shields.io/badge/Vue.js-3.x-4FC08D?logo=vuedotjs&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-4169E1?logo=postgresql&logoColor=white)
![DeepSeek](https://img.shields.io/badge/DeepSeek-API-blue)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## Overview

PaperInsight automatically fetches papers from arXiv, analyzes their relevance to your research focus using DeepSeek LLM, and presents them in a clean, modern dashboard with AI-generated insights.

### Key Features

- **Automated Paper Fetching** — Daily retrieval from arXiv based on configurable research topics
- **AI-Powered Analysis** — DeepSeek generates Chinese summaries, relevance scores, and heuristic research ideas
- **Smart Filtering** — Filter papers by relevance score (High/Medium/Low) and processing status
- **Modern Dashboard** — Clean, academic-yet-modern UI inspired by Linear and Vercel's design language
- **Expandable Cards** — Click to reveal full abstracts, relevance reasoning, and PDF links

## Tech Stack

| Layer | Technology |
|-------|------------|
| Frontend | Vue 3, TypeScript, Vite, Tailwind CSS |
| Backend | FastAPI, SQLModel, PostgreSQL |
| AI | DeepSeek API (OpenAI-compatible) |
| Data Source | arXiv API |

## Quick Start

### Prerequisites

- Python 3.12+
- Node.js 18+ & pnpm
- PostgreSQL 15+
- DeepSeek API Key

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

# Start PostgreSQL database using Docker
docker run --name paper-insight-db -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=paper_insight -p 5432:5432 -d postgres:latest

# Configure environment
cp .env.example .env
# Edit .env and add your DEEPSEEK_API_KEY

# Run the server
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
# Database
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/paper_insight

# DeepSeek API
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### Research Focus

Edit `backend/app/services/arxiv_bot.py` to customize search queries:

```python
SEARCH_QUERIES = [
    "Diffusion Transformer DiT",
    "autoregressive image generation",
    "KV cache compression LLM",
    # Add your research topics...
]
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/papers` | List papers with filters |
| `GET` | `/papers/{id}` | Get paper by ID |
| `POST` | `/papers/fetch` | Trigger paper fetching |
| `POST` | `/papers/{id}/process` | Process paper with LLM |
| `GET` | `/stats` | Get statistics |

### Query Parameters

```
GET /papers?skip=0&limit=20&min_score=7&processed_only=true
```

## Project Structure

```
paper-insight/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI application
│   │   ├── models.py        # SQLModel schemas
│   │   ├── database.py      # Database connection
│   │   └── services/
│   │       ├── arxiv_bot.py # arXiv fetcher
│   │       └── llm_brain.py # DeepSeek client
│   ├── .env.example
│   └── pyproject.toml
│
└── frontend/
    ├── src/
    │   ├── components/
    │   │   ├── layout/      # AppSidebar
    │   │   ├── paper/       # PaperCard
    │   │   └── ui/          # RelevanceBadge, HeuristicBox
    │   ├── services/        # API client
    │   ├── types/           # TypeScript types
    │   ├── App.vue
    │   └── style.css        # Design system
    ├── package.json
    └── vite.config.ts
```

## Screenshots

*Coming soon*

## Roadmap

- [ ] Full-text search across papers
- [ ] Scheduled automatic fetching (APScheduler)
- [ ] Export to Notion/Obsidian
- [ ] Paper collections/bookmarks
- [ ] Email digest notifications
- [ ] Multi-language summary support

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
- [DeepSeek](https://deepseek.com/) for the powerful LLM API
- Design inspiration from [Linear](https://linear.app/) and [Vercel](https://vercel.com/)
