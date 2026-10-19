# PaperInsight backend

FastAPI app that powers the PaperInsight Mac app: arXiv fetching, the analysis pipeline
(MinerU → vision model → reasoning model), settings and the local MinerU runtime.
`app/desktop.py` wraps it in a native window; see the top-level README for building the app.

```bash
uv sync
PAPER_INSIGHT_DATA_DIR=/tmp/paper-insight-dev uv run uvicorn app.main:app --reload --port 8000
uv run pytest
```
