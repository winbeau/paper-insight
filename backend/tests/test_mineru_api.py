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


def test_kill_now_is_fast_even_if_server_ignores_sigterm(tmp_path):
    import subprocess
    import sys
    import time

    runtime = MineruRuntime(root=tmp_path / "mineru")
    runtime.root.mkdir(parents=True)
    stubborn = subprocess.Popen(
        [sys.executable, "-c", "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"],
        start_new_session=True,
    )
    time.sleep(0.3)  # let it install the handler
    runtime._server = stubborn
    runtime.pid_path.write_text(str(stubborn.pid))

    started = time.monotonic()
    runtime.kill_now(grace=0.5)
    stubborn.wait(timeout=5)
    assert time.monotonic() - started < 1.5
    assert not runtime.pid_path.exists() and runtime._server is None
