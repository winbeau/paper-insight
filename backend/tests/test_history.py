from datetime import datetime

import app.services.analyzer as analyzer
from app.config import ensure_dirs, parsed_dir_for, pdf_path_for, thumbnail_path_for, thumbnail_url_for
from app.database import get_sync_session
from app.models import Paper, ResearchDirection


def setup_papers():
    """Direction A: p1 (shared arXiv id), p2 (skipped); direction B: p3 (same arXiv id as p1)."""
    ensure_dirs()
    with get_sync_session() as session:
        a = ResearchDirection(name="A", position=0)
        b = ResearchDirection(name="B", position=1)
        session.add(a)
        session.add(b)
        session.commit()

        def paper(arxiv_id, direction, status="pending", title="Paper"):
            p = Paper(arxiv_id=arxiv_id, title=title, authors="x", abstract="y", categories="cs.CV",
                      published=datetime(2024, 1, 1), updated=datetime(2024, 1, 1), pdf_url="u",
                      direction_id=direction.id, processing_status=status,
                      thumbnail_url=thumbnail_url_for(arxiv_id))
            session.add(p)
            session.commit()
            return p.id

        ids = {
            "p1": paper("2401.00001v1", a, "processed", "Shared diffusion paper"),
            "p2": paper("2401.00002v1", a, "skipped", "Unrelated robotics"),
            "p3": paper("2401.00001v1", b, "pending", "Shared diffusion paper"),
        }
        return a.id, b.id, ids


def make_files(arxiv_id):
    pdf_path_for(arxiv_id).write_bytes(b"%PDF-" + b"0" * 1000)
    thumb = thumbnail_path_for(thumbnail_url_for(arxiv_id))
    thumb.parent.mkdir(parents=True, exist_ok=True)
    thumb.write_bytes(b"jpg" * 100)
    parsed = parsed_dir_for(arxiv_id)
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "markdown.md").write_text("# x" * 100)


def files_exist(arxiv_id):
    return pdf_path_for(arxiv_id).exists() and parsed_dir_for(arxiv_id).exists()


def test_list_filters_and_includes_skipped(client):
    a, b, ids = setup_papers()
    body = client.get("/api/history").json()
    assert body["total"] == 3 and {i["direction_name"] for i in body["items"]} == {"A", "B"}
    assert client.get(f"/api/history?direction_id={a}").json()["total"] == 2
    assert [i["id"] for i in client.get("/api/history?status=skipped").json()["items"]] == [ids["p2"]]
    assert client.get("/api/history?q=robotics").json()["total"] == 1
    assert client.get("/api/history?q=2401.00001").json()["total"] == 2
    assert set(body["storage"]) == {"pdfs", "parsed", "thumbnails", "total"}


def test_delete_keeps_files_shared_with_another_direction(client):
    a, b, ids = setup_papers()
    make_files("2401.00001v1")
    result = client.post("/api/history/delete", json={"paper_ids": [ids["p1"]]}).json()
    assert result == {"deleted": 1, "skipped_active": 0, "freed_bytes": 0}
    assert files_exist("2401.00001v1")  # direction B still has the paper

    result = client.post("/api/history/delete", json={"paper_ids": [ids["p3"]]}).json()
    assert result["deleted"] == 1 and result["freed_bytes"] > 0
    assert not files_exist("2401.00001v1")


def test_delete_can_keep_files(client):
    a, b, ids = setup_papers()
    make_files("2401.00002v1")
    client.post("/api/history/delete", json={"paper_ids": [ids["p2"]], "delete_files": False})
    assert files_exist("2401.00002v1")


def test_running_papers_are_not_deleted(client, monkeypatch):
    a, b, ids = setup_papers()
    monkeypatch.setattr(analyzer, "_active", {ids["p1"]})
    result = client.post("/api/history/delete", json={"paper_ids": [ids["p1"], ids["p2"]]}).json()
    assert (result["deleted"], result["skipped_active"]) == (1, 1)
    assert client.delete(f"/api/papers/{ids['p1']}").status_code == 409


def test_clear_by_direction_and_status(client):
    a, b, ids = setup_papers()
    assert client.post("/api/history/clear", json={"direction_id": a, "status": "skipped"}).json()["deleted"] == 1
    assert client.post("/api/history/clear", json={"direction_id": a}).json()["deleted"] == 1
    remaining = client.get("/api/history").json()["items"]
    assert [i["id"] for i in remaining] == [ids["p3"]]


def test_card_delete_keeps_shared_cache(client):
    a, b, ids = setup_papers()
    make_files("2401.00001v1")
    assert client.delete(f"/api/papers/{ids['p1']}").status_code == 200
    assert files_exist("2401.00001v1")


def test_prune_removes_only_orphan_files(client):
    setup_papers()
    make_files("2401.00001v1")
    make_files("2399.99999v1")  # no paper references it
    result = client.post("/api/history/prune").json()
    assert result["removed"] == 3 and result["freed_bytes"] > 0
    assert files_exist("2401.00001v1") and not files_exist("2399.99999v1")
