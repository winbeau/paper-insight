import sqlite3

from sqlalchemy import create_engine

import app.database as database
from app.schemas import MASK_PREFIX

SECRET = "sk-abcdefghijklmnop1234"


def test_provider_key_is_masked_and_preserved(client):
    provider = {"id": "ds", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "api_key": SECRET}
    res = client.put("/api/settings", json={
        "providers": [provider],
        "pipeline": {"reasoning": {"provider_id": "ds", "model": "deepseek-reasoner"},
                     "parser": {"cloud": {"token": "mineru-token-xyz123"}}},
    })
    assert res.status_code == 200
    body = res.json()
    masked_key = body["providers"][0]["api_key"]
    assert masked_key.startswith(MASK_PREFIX) and SECRET not in res.text
    assert body["pipeline"]["parser"]["cloud"]["token"].startswith(MASK_PREFIX)

    # Round-trip what the UI got back (masked values) plus an unrelated change
    body["research_idea"] = "我的研究"
    res = client.put("/api/settings", json=body)
    assert res.status_code == 200

    from app.database import get_sync_session
    from app.models import AppSettings

    with get_sync_session() as session:
        row = session.get(AppSettings, 1)
        assert row.providers[0]["api_key"] == SECRET
        assert row.pipeline["parser"]["cloud"]["token"] == "mineru-token-xyz123"
        assert row.research_idea == "我的研究"


def test_partial_update_keeps_other_fields(client):
    client.put("/api/settings", json={"research_idea": "idea", "arxiv_categories": ["cs.CL"]})
    res = client.put("/api/settings", json={"research_focus": 'abs:"kv cache" OR abs:pruning'})
    body = res.json()
    assert body["research_idea"] == "idea"
    assert body["arxiv_categories"] == ["cs.CL"]
    assert body["focus_keywords"] == ["kv cache", "pruning"]


def test_new_key_replaces_old(client):
    provider = {"id": "ds", "name": "x", "base_url": "https://a", "api_key": SECRET}
    client.put("/api/settings", json={"providers": [provider]})
    client.put("/api/settings", json={"providers": [{**provider, "api_key": "sk-new-key-0000000000"}]})
    from app.database import get_sync_session
    from app.models import AppSettings

    with get_sync_session() as session:
        assert session.get(AppSettings, 1).providers[0]["api_key"] == "sk-new-key-0000000000"


def test_legacy_schema_is_migrated(tmp_path, monkeypatch):
    """A pre-refactor DB (Dify era) gains the new columns and keeps its data."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE appsettings (id INTEGER PRIMARY KEY, research_focus TEXT, research_idea TEXT,
            focus_keywords JSON, system_prompt TEXT, arxiv_categories JSON);
        INSERT INTO appsettings VALUES (1, 'abs:DiT', 'old idea', '["DiT"]', NULL, '["cs.CV"]');
        CREATE TABLE paper (id INTEGER PRIMARY KEY, arxiv_id TEXT, title TEXT, authors TEXT, abstract TEXT,
            categories TEXT, published DATETIME, updated DATETIME, pdf_url TEXT, thumbnail_url TEXT,
            paper_essence TEXT, concept_bridging TEXT, visual_verification TEXT, relevance_score FLOAT,
            relevance_reason TEXT, heuristic_suggestion TEXT, is_processed BOOLEAN, processing_status TEXT,
            created_at DATETIME, processed_at DATETIME);
        INSERT INTO paper (id, arxiv_id, title, authors, abstract, categories, published, updated, pdf_url,
            is_processed, processing_status, created_at)
            VALUES (1, '2401.1', 't', 'a', 'abs', 'cs.CV', '2024-01-01', '2024-01-01', 'u', 0, 'processing', '2024-01-01');
    """)
    conn.close()

    monkeypatch.setattr(database, "engine", create_engine(f"sqlite:///{db_path}"))
    database.ensure_appsettings_schema()
    database.ensure_paper_schema()
    assert database.reset_interrupted_processing() == 1

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT research_idea, providers, pipeline, system_prompt FROM appsettings").fetchone()
    assert row == ("old idea", "[]", "{}", "")
    status = conn.execute("SELECT processing_status, processing_error FROM paper").fetchone()
    assert status == ("failed", "interrupted")
    conn.close()

    from app.models import AppSettings
    from app.schemas import load_settings
    from sqlmodel import Session

    with Session(database.engine) as session:
        settings = load_settings(session.get(AppSettings, 1))
    assert settings.research_idea == "old idea" and settings.pipeline.parser.engine == "mineru_local"


def test_fresh_install_defaults_to_deepseek_flash(client):
    body = client.get("/api/settings").json()
    assert body["providers"] == [{
        "id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com",
        "api_key": "", "json_mode": False,
    }]
    for step in ("reasoning", "vision"):
        assert body["pipeline"][step]["provider_id"] == "deepseek"
        assert body["pipeline"][step]["model"] == "deepseek-flash"

    # Saving just the key makes the default usable; the default provider is persisted
    body["providers"][0]["api_key"] = SECRET
    client.put("/api/settings", json=body)
    from app.services.analyzer import reasoning_configured
    assert reasoning_configured()


def test_default_provider_without_key_is_not_configured(client):
    client.get("/api/settings")
    from app.services.analyzer import reasoning_configured
    assert not reasoning_configured()


def test_local_provider_needs_no_key():
    from app.schemas import Provider

    assert not Provider(base_url="http://localhost:11434/v1").needs_api_key
    assert Provider(base_url="https://api.deepseek.com").needs_api_key
