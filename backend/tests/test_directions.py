import asyncio
import contextlib
import json
import sqlite3
from datetime import datetime

from sqlalchemy import create_engine
from sqlmodel import Session, select

import app.database as database
import app.services.analyzer as analyzer
import app.services.parse_queue as parse_queue
from app.database import ensure_default_direction, get_sync_session
from app.models import AppSettings, Paper, PaperCreate, ResearchDirection
from app.services.arxiv_bot import ArxivBot
from app.services.parsers.base import ParsedDocument


def paper_data(arxiv_id="2401.00001v1"):
    return PaperCreate(arxiv_id=arxiv_id, title="T", authors="A", abstract="abs", categories="cs.CV",
                       published=datetime(2024, 1, 1), updated=datetime(2024, 1, 1), pdf_url="https://x")


def two_directions():
    with get_sync_session() as session:
        a = ResearchDirection(name="视频加速", position=0, research_idea="IDEA-A")
        b = ResearchDirection(name="机器人", position=1, research_idea="IDEA-B")
        session.add(a)
        session.add(b)
        session.commit()
        return a.id, b.id


def test_same_arxiv_paper_can_live_in_two_directions():
    a, b = two_directions()
    bot = ArxivBot()
    with get_sync_session() as session:
        assert bot.save_paper(session, paper_data(), a) is not None
        assert bot.save_paper(session, paper_data("2401.00001v2"), a) is None  # other version: same paper
        assert bot.save_paper(session, paper_data(), b) is not None
        assert len(session.exec(select(Paper)).all()) == 2


def test_settings_sync_creates_renames_and_deletes_directions(client):
    body = client.get("/api/settings").json()
    assert [d["name"] for d in body["directions"]] == ["研究方向 1"]  # created on startup
    first = body["directions"][0]
    body["directions"] = [
        {**first, "name": "视频加速", "research_focus": 'abs:"kv cache"; abs:DiT'},
        {"name": "机器人", "arxiv_categories": ["cs.RO"], "research_idea": "抓取"},
    ]
    saved = client.put("/api/settings", json=body).json()["directions"]
    assert [d["name"] for d in saved] == ["视频加速", "机器人"]
    assert saved[0]["id"] == first["id"] and saved[1]["id"] is not None
    assert saved[0]["focus_keywords"] == ['abs:"kv cache"', "abs:DiT"]

    with get_sync_session() as session:
        session.add(Paper(**paper_data().model_dump(), direction_id=saved[1]["id"]))
        session.commit()
    summary = {d["name"]: d for d in client.get("/api/directions").json()}
    assert summary["机器人"]["total"] == 1 and summary["机器人"]["pending"] == 1

    # Dropping a direction deletes its papers
    saved = client.put("/api/settings", json={"directions": [saved[0]]}).json()["directions"]
    assert [d["name"] for d in saved] == ["视频加速"]
    with get_sync_session() as session:
        assert session.exec(select(Paper)).all() == []
    assert client.put("/api/settings", json={"directions": []}).status_code == 400


def test_papers_and_stats_filter_by_direction(client):
    a, b = two_directions()
    with get_sync_session() as session:
        session.add(Paper(**paper_data("2401.00001v1").model_dump(), direction_id=a))
        session.add(Paper(**paper_data("2401.00002v1").model_dump(), direction_id=b))
        session.add(Paper(**paper_data("2401.00003v1").model_dump(), direction_id=b))
        session.commit()
    assert len(client.get(f"/api/papers?direction_id={b}").json()) == 2
    assert client.get(f"/api/stats?direction_id={a}").json()["total_papers"] == 1
    assert len(client.get(f"/api/papers/pending?direction_id={b}").json()["paper_ids"]) == 2


def test_legacy_single_direction_db_is_migrated(tmp_path, monkeypatch):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE appsettings (id INTEGER PRIMARY KEY, research_focus TEXT, research_idea TEXT,
            focus_keywords JSON, system_prompt TEXT, arxiv_categories JSON);
        INSERT INTO appsettings VALUES (1, 'abs:DiT', 'old idea', '["DiT"]', '', '["cs.CV"]');
        CREATE TABLE paper (id INTEGER PRIMARY KEY, arxiv_id VARCHAR NOT NULL, title VARCHAR, authors VARCHAR,
            abstract TEXT, categories VARCHAR, published DATETIME, updated DATETIME, pdf_url VARCHAR,
            thumbnail_url VARCHAR, paper_essence TEXT, concept_bridging TEXT, visual_verification TEXT,
            relevance_score FLOAT, relevance_reason TEXT, heuristic_suggestion TEXT, is_processed BOOLEAN,
            processing_status VARCHAR, created_at DATETIME, processed_at DATETIME);
        CREATE UNIQUE INDEX ix_paper_arxiv_id ON paper (arxiv_id);
        INSERT INTO paper (id, arxiv_id, title, authors, abstract, categories, published, updated, pdf_url,
            is_processed, processing_status, created_at)
            VALUES (1, '2401.1', 't', 'a', 'abs', 'cs.CV', '2024-01-01', '2024-01-01', 'u', 0, 'pending', '2024-01-01');
    """)
    conn.close()

    engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(database, "engine", engine)
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(engine)  # adds the new researchdirection table
    database.ensure_appsettings_schema()
    database.ensure_paper_schema()
    direction_id = ensure_default_direction()

    with Session(engine) as session:
        direction = session.get(ResearchDirection, direction_id)
        assert (direction.research_focus, direction.research_idea, direction.arxiv_categories) == (
            "abs:DiT", "old idea", ["cs.CV"])
        assert session.get(Paper, 1).direction_id == direction_id
    conn = sqlite3.connect(db_path)
    # the same arXiv id may now exist in a second direction
    conn.execute("INSERT INTO paper (arxiv_id, title, authors, abstract, categories, published, updated, pdf_url, "
                 "is_processed, processing_status, created_at, direction_id) "
                 "VALUES ('2401.1','t','a','abs','cs.CV','2024','2024','u',0,'pending','2024', 999)")
    conn.commit()
    conn.close()


async def test_each_direction_analyzes_with_its_own_idea_sharing_parse_and_vision(monkeypatch, tmp_path):
    a, b = two_directions()
    with get_sync_session() as session:
        session.add(AppSettings(
            id=1,
            providers=[{"id": "p", "name": "P", "base_url": "https://llm.test/v1", "api_key": "k"}],
            pipeline={"parser": {"engine": "mineru_cloud", "cloud": {"token": "t"}},
                      "vision": {"provider_id": "p", "model": "vl"},
                      "reasoning": {"provider_id": "p", "model": "r1"}},
        ))
        ids = []
        for direction_id in (a, b):
            paper = Paper(**paper_data().model_dump(), direction_id=direction_id)
            session.add(paper)
            session.commit()
            ids.append(paper.id)

    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "f.jpg").write_bytes(b"x" * 10000)
    (tmp_path / "p.pdf").write_bytes(b"%PDF-")
    counts = {"parse": 0, "vision": 0}
    prompts = []

    async def fake_pdf(arxiv_id, url):
        return tmp_path / "p.pdf"

    async def fake_parse(config, request, progress):
        counts["parse"] += 1
        await asyncio.sleep(0.05)
        from app.services.parsers.base import Figure
        return ParsedDocument(root=tmp_path, markdown="# P", engine="mineru_cloud",
                              figures=[Figure(n=1, kind="image", path="images/f.jpg", caption="Figure 1: x")])

    async def fake_vision(doc, figures, provider, config, title, progress, abstract=""):
        counts["vision"] += 1
        await asyncio.sleep(0.05)
        return "[Figure 1] x — y"

    async def fake_llm(provider, model, messages, **kwargs):
        prompts.append(messages[1]["content"])
        yield "answer", json.dumps({"paper_essence": "e", "relevance_score": 6})

    async def fake_thumb(arxiv_id, pdf_path):
        return None

    monkeypatch.setattr(parse_queue, "_queue", None)
    monkeypatch.setattr(parse_queue, "ensure_pdf", fake_pdf)
    monkeypatch.setattr(parse_queue, "parse_document", fake_parse)
    monkeypatch.setattr(analyzer, "ensure_pdf", fake_pdf)
    monkeypatch.setattr(analyzer, "build_visual_evidence", fake_vision)
    monkeypatch.setattr(analyzer, "stream_chat", fake_llm)
    monkeypatch.setattr(analyzer, "generate_thumbnail", fake_thumb)

    async def run(paper_id):
        async with contextlib.aclosing(analyzer.process_paper(paper_id)) as events:
            async for _ in events:
                pass

    await asyncio.gather(*(run(pid) for pid in ids))
    assert counts == {"parse": 1, "vision": 1}  # shared across directions
    assert sorted(p.split("## 我的研究 Idea\n")[1].split("\n")[0] for p in prompts) == ["IDEA-A", "IDEA-B"]
