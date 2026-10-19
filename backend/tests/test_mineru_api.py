import asyncio

import app.services.mineru_runtime as runtime_module
from app.services.mineru_runtime import MineruRuntime


def test_install_endpoint_starts_background_job_and_streams_log(client, monkeypatch, tmp_path):
    runtime = MineruRuntime(root=tmp_path / "mineru")
    monkeypatch.setattr(runtime_module, "_runtime", runtime)

    async def fake_install(tier, source):
        runtime._log(f"installing tier={tier} source={source}")
        await asyncio.sleep(0.05)
        runtime._log("done")

    monkeypatch.setattr(runtime, "_install", fake_install)

    res = client.post("/api/mineru/install", json={"tier": "basic", "source": "modelscope"})
    assert res.status_code == 200, res.text
    assert res.json()["install"]["running"] is True

    with client.stream("GET", "/api/mineru/install/stream") as stream:
        body = "".join(stream.iter_text())
    assert "installing tier=basic source=modelscope" in body
    assert "event: done" in body

    status = client.get("/api/mineru/status").json()
    assert status["installed"] is False and status["install"]["running"] is False
