<div align="right">
  <a href="README.md">English</a> | <a href="README_zh.md">中文</a>
</div>

<p align="center">
  <img src="frontend/public/logo.svg" alt="PaperInsight logo" width="160" style="margin-bottom: 6px;" />
</p>
<h1 align="center" style="margin-top: 0; margin-bottom: 6px; font-size: 2.75rem;">PaperInsight</h1>

<p align="center" style="margin-top: 0; margin-bottom: 6px;">A macOS app that tracks arXiv papers and analyzes them against your research idea.</p>

<p align="center" style="margin-top: 0;">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-000000?logo=apple&logoColor=white" alt="macOS" />
  <img src="https://img.shields.io/badge/Vue.js-3.x-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue.js" />
  <img src="https://img.shields.io/badge/FastAPI-0.128-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/MinerU-4.x-blue" alt="MinerU" />
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License" />
</p>

## Overview

PaperInsight fetches new papers from arXiv every day, parses each PDF with **MinerU**, reads its figures with a **vision model**, and has a **reasoning model** judge how the paper relates to your research idea — all inside a native macOS window. Every model-backed step is configurable and talks to any **OpenAI-compatible API**.

Out of the box it parses PDFs with a local MinerU (one-click install from Settings) and uses **DeepSeek-V4.1-Flash** (`deepseek-flash`, text + image) for both the vision and the reasoning step: install MinerU, enter a DeepSeek API key, and you're done.

### Analysis pipeline

```
download PDF ─▶ ① parse / OCR (MinerU cloud | MinerU local) ─▶ ② figure recognition (vision LLM) ─▶ ③ reasoning (LLM, streamed) ─▶ result
```

| Step | Engine | Configurable |
|------|--------|--------------|
| ① Parse / OCR | MinerU cloud (mineru.net API) or MinerU local (installed and run by the app) | engine, model version / tier, OCR, formula & table recognition |
| ② Figure recognition | any OpenAI-compatible vision model | provider, model, max figures, concurrency |
| ③ Reasoning | any OpenAI-compatible model; reasoning tokens stream live into the card | provider, model, temperature, max tokens, input size, prompt |

Each paper gets: core innovation, concept bridging to your idea, figure-grounded verification ("Figure 3 supports…"), a 0–10 relevance score and concrete experiment suggestions.

### Features

- **Native Mac app** — one window, no server to run; data stays on your Mac
- **Multiple research directions** — each with its own arXiv query, research idea and scoring prompt; one tab per direction in Settings and in the feed. A paper that matches several directions is analyzed once per direction, while PDF, MinerU parse and figure evidence are shared
- **AI-assisted setup** — describe your research in plain words (✨ on each direction page); the reasoning model fills in categories, query, research idea and scoring rubric, and tests the query against live arXiv over several rounds (weekly volume + relevance of sample papers), keeping the best tested query
- **Parsing runs ahead** — starting a batch queues MinerU for every paper at once; each paper's vision and reasoning steps run while MinerU already parses the next one. **Stop Processing** ends every run (UI, scheduler, MinerU) with one click; stopped papers return to pending
- **Prompt-cache friendly** — prompts keep a byte-stable prefix (system prompt + research idea; shared paper context for figures; append-only agent conversation), so DeepSeek serves most input from its cache. The hit rate is shown per paper and at `/api/usage`
- **Daily fetching** — 06:00 local time, with a catch-up run if the Mac was asleep
- **Configurable models** — add DeepSeek, OpenAI, DashScope, SiliconFlow, Zhipu, Moonshot, OpenRouter, Ollama, LM Studio or any compatible endpoint; test them and list their models from Settings
- **Local MinerU** — one click installs MinerU and pulls its model checkpoints into the app's data dir; the server starts on demand and stops when idle
- **Live progress** — per-step progress and streamed reasoning on every card
- **arXiv import, filters, PDF thumbnails, structured logs**

## Install

Build the app (Apple Silicon, macOS 13+):

```bash
brew install uv pnpm      # if needed
./scripts/build_mac.sh    # → dist/PaperInsight.app and dist/PaperInsight.dmg
```

Open the DMG and drag **PaperInsight** to Applications. The build is ad-hoc signed (not notarized): on first launch, right-click the app → **Open**.

## Setup

Open **Settings**:

1. **Model providers** — DeepSeek is preconfigured: paste your API key. Add other providers if you want different models per step.
2. **Pipeline**
   - **① MinerU**: either paste a token from [mineru.net](https://mineru.net) → API management (cloud), or choose **MinerU local** → **Install and pull models**. The local install needs ~3–6 GB of disk (16 GB RAM recommended); pick ModelScope as the model source if Hugging Face is slow for you. You can also point it at an existing `mineru-kit api-server`.
   - **② Vision / ③ Reasoning**: defaults to `deepseek-flash`; use **Test** to check a model.
3. **Research directions** — one sub-tab per direction (**+** adds one): arXiv categories, the search query, your research idea (the context papers are scored against) and an optional scoring prompt. **✨ AI 帮我填写** (bottom-left of each page) fills all four from a plain-language description.
4. **Proxy** (optional) — apps launched from Finder don't inherit shell proxy variables; set one here if arXiv / APIs need it.

If MinerU fails on a paper, the paper is marked failed and can be retried.

## Data

| What | Where |
|------|-------|
| Database (papers, settings, API keys) | `~/Library/Application Support/PaperInsight/paper_insight.db` (mode 0600) |
| PDFs, MinerU output, thumbnails | `~/Library/Application Support/PaperInsight/{pdfs,parsed,thumbnails}/` |
| Local MinerU (env, models) | `~/Library/Application Support/PaperInsight/mineru/` |
| Logs | `~/Library/Logs/PaperInsight/app.log`, `mineru.log` |

**Migrating from the server version:** quit the app, copy your old `paper_insight.db` to `~/Library/Application Support/PaperInsight/`, and start it again — the schema is upgraded automatically. Missing thumbnails are regenerated the next time a paper is analyzed.

## Development

```bash
# backend (API on :8000, data in a scratch dir)
cd backend
uv sync
PAPER_INSIGHT_DATA_DIR=/tmp/paper-insight-dev uv run uvicorn app.main:app --reload --port 8000

# frontend (Vite on :5173, proxies /api to :8000)
cd frontend
pnpm install
pnpm dev

# desktop window around the built frontend
pnpm -C frontend build
cd backend && uv run python -m app.desktop

# tests
cd backend && uv run pytest
```

### Project structure

```
paper-insight/
├── backend/app/
│   ├── main.py              # FastAPI app: /api routes, thumbnails, built UI, scheduler
│   ├── desktop.py           # Mac app entry: local server thread + pywebview window
│   ├── config.py            # data / log / bundle paths
│   ├── schemas.py           # providers + per-step pipeline settings
│   ├── prompts.py           # analysis & vision prompts
│   ├── api/                 # papers, processing (SSE), settings, providers, mineru, stats
│   └── services/
│       ├── analyzer.py      # the pipeline (download → parse → vision → reasoning)
│       ├── llm_client.py    # OpenAI-compatible streaming client
│       ├── parsers/         # MinerU cloud + local clients, output normalization
│       ├── mineru_runtime.py# installs / runs the local MinerU server
│       ├── vision.py        # figure selection + visual evidence
│       ├── arxiv_bot.py     # arXiv fetching
│       └── pdf_renderer.py  # PDF cache + thumbnails
├── frontend/src/            # Vue 3 UI (settings tabs in components/settings/)
├── packaging/               # PyInstaller spec, launcher, icon generator
└── scripts/build_mac.sh     # builds the .app and .dmg
```

The local API listens on `127.0.0.1` only and rejects requests from other hosts and cross-site origins.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

- [arXiv](https://arxiv.org/) for open access to research papers
- [MinerU](https://github.com/opendatalab/MinerU) for PDF parsing
- [DeepSeek](https://deepseek.com/) for the default models
- [pywebview](https://pywebview.flowrl.com/) for the native window
