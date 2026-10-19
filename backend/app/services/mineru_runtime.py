"""Managed local MinerU runtime.

The app can't bundle MinerU (torch + models are several GB), so it installs it on demand
into its data dir with uv, pulls the model checkpoints there, and runs
`mineru-kit api-server` as a child process when a paper needs parsing:

    mineru/venv/          Python env with `mineru` (CPython managed by uv in mineru/python/)
    mineru/config.yaml    MINERU_CONFIG — points model.base_dir at mineru/models/
    mineru/models/        downloaded checkpoints
    mineru/install.json   what was installed (tier, source, version)
    mineru/server.pid     pid of a running api-server (for cleanup after a crash)

The server runs in its own process group so it can be killed with everything it spawns,
and is stopped after IDLE_SHUTDOWN seconds without work to free memory.
"""

import asyncio
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

import httpx

from app.config import DATA_DIR, IS_FROZEN, LOG_DIR, MINERU_DIR, bundled_bin_dir
from app.logging_config import get_logger
from app.services.errors import PipelineError

logger = get_logger("services.mineru_runtime")

MINERU_REQUIREMENT = "mineru>=4.0,<5"
PYTHON_VERSION = "3.12"
MIN_FREE_BYTES = 8 * 1024**3
SERVER_START_TIMEOUT = 600   # first start loads models
IDLE_SHUTDOWN = 10 * 60
LOG_TAIL = 400
UPLOAD_DIR = DATA_DIR / "mineru-uploads"


def find_uv() -> Optional[str]:
    candidates: List[Optional[str]] = []
    bundled = bundled_bin_dir()
    if bundled:
        candidates.append(str(bundled / "uv"))
    candidates.append(shutil.which("uv"))
    home = Path.home()
    candidates += [
        "/opt/homebrew/bin/uv",
        "/usr/local/bin/uv",
        str(home / ".local" / "bin" / "uv"),
        str(home / ".cargo" / "bin" / "uv"),
    ]
    for candidate in candidates:
        if candidate and os.access(candidate, os.X_OK):
            return candidate
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class MineruRuntime:
    def __init__(self, root: Path = MINERU_DIR):
        self.root = root
        self.venv = root / "venv"
        self.python_dir = root / "python"
        self.models_dir = root / "models"
        self.config_path = root / "config.yaml"
        self.state_path = root / "install.json"
        self.pid_path = root / "server.pid"
        self.log_path = LOG_DIR / "mineru.log"

        # install job
        self._install_task: Optional[asyncio.Task] = None
        self._install_proc: Optional[asyncio.subprocess.Process] = None
        self._install_log: Deque[str] = deque(maxlen=LOG_TAIL)
        self._install_seq = 0
        self._install_step = ""
        self._install_error: Optional[str] = None
        self._install_event = asyncio.Event()

        # api-server
        self._server: Optional[subprocess.Popen] = None
        self._server_url: Optional[str] = None
        self._server_tier: Optional[str] = None
        self._server_concurrency = 1
        self._server_lock = asyncio.Lock()
        self._busy = 0
        self._last_used = 0.0
        self._idle_task: Optional[asyncio.Task] = None

    # --- paths / env -------------------------------------------------------------

    @property
    def bin_dir(self) -> Path:
        return self.venv / "bin"

    def _env(self, source: Optional[str] = None) -> Dict[str, str]:
        env = dict(os.environ)
        if IS_FROZEN:
            # Don't leak the frozen app's interpreter settings into the venv's Python
            for key in list(env):
                if key.startswith(("_PYI", "_MEI")) or key in (
                    "PYTHONHOME", "PYTHONPATH", "DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"
                ):
                    env.pop(key, None)
        env.update({
            "MINERU_CONFIG": str(self.config_path),
            "UV_PYTHON_INSTALL_DIR": str(self.python_dir),
            "HF_HOME": str(self.root / "hf-cache"),
            "MODELSCOPE_CACHE": str(self.root / "modelscope-cache"),
            "PATH": f"{self.bin_dir}:{env.get('PATH', '/usr/bin:/bin')}",
            "VIRTUAL_ENV": str(self.venv),
            "PYTHONUNBUFFERED": "1",
        })
        if source:
            env["MINERU_MODEL_SOURCE"] = source
        return env

    def _state(self) -> Dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def is_installed(self) -> bool:
        return bool(self._state().get("installed_at")) and (self.bin_dir / "mineru-kit").exists()

    # --- status ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        state = self._state()
        return {
            "installed": self.is_installed(),
            "tier": state.get("tier"),
            "source": state.get("source"),
            "version": state.get("version"),
            "installed_at": state.get("installed_at"),
            "uv_available": find_uv() is not None,
            "server_running": self._server_alive(),
            "server_url": self._server_url if self._server_alive() else None,
            "busy": self._busy > 0,
            "install": {
                "running": self.install_running(),
                "step": self._install_step,
                "error": self._install_error,
                "log_tail": list(self._install_log)[-40:],
            },
            "disk_free_gb": round(shutil.disk_usage(self.root if self.root.exists() else Path.home()).free / 1024**3, 1),
        }

    # --- install -----------------------------------------------------------------

    def install_running(self) -> bool:
        return self._install_task is not None and not self._install_task.done()

    def start_install(self, tier: str, source: str) -> None:
        """Start the install job in the background. Must be called on the event loop."""
        if self.install_running():
            return
        self._install_log.clear()
        self._install_error = None
        self._install_step = "准备安装"
        self._install_task = asyncio.create_task(self._install(tier, source))

    async def cancel_install(self) -> None:
        if self._install_proc and self._install_proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(self._install_proc.pid, signal.SIGTERM)
        if self._install_task:
            self._install_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._install_task

    def _log(self, line: str) -> None:
        line = line.rstrip()
        if not line:
            return
        self._install_log.append(line)
        self._install_seq += 1
        self._install_event.set()
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} | install | {line}\n")
        except OSError:
            pass

    async def _run(self, step: str, *args: str, env: Dict[str, str]) -> None:
        self._install_step = step
        self._log(f"==> {step}")
        self._log("$ " + " ".join(args))
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            cwd=str(self.root),
            start_new_session=True,
        )
        self._install_proc = proc
        assert proc.stdout is not None
        buffer = b""
        last_progress_log = 0.0
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            buffer += chunk
            # Progress bars redraw with \r: keep only the latest state of such lines
            *lines, buffer = buffer.replace(b"\r", b"\n").split(b"\n")
            for raw in lines:
                text = raw.decode("utf-8", errors="replace")
                is_progress = "%" in text and ("|" in text or "it/s" in text or "MB" in text)
                now = time.monotonic()
                if is_progress and now - last_progress_log < 1.0:
                    continue
                last_progress_log = now if is_progress else last_progress_log
                self._log(text)
        if buffer:
            self._log(buffer.decode("utf-8", errors="replace"))
        code = await proc.wait()
        self._install_proc = None
        if code != 0:
            raise RuntimeError(f"{step} 失败 (exit {code})")

    def _write_config(self, source: str) -> None:
        # JSON strings are valid YAML scalars (handles spaces in "Application Support")
        self.config_path.write_text(
            "model:\n"
            f"  source: {json.dumps(source)}\n"
            f"  base_dir: {json.dumps(str(self.models_dir))}\n"
            "  small_backend: auto\n"
            "  vlm:\n"
            "    engine: auto\n",
            encoding="utf-8",
        )

    async def _install(self, tier: str, source: str) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            uv = find_uv()
            if not uv:
                raise RuntimeError("未找到 uv（应用内置的 uv 缺失；可用 `brew install uv` 安装）")
            free = shutil.disk_usage(self.root).free
            if free < MIN_FREE_BYTES:
                raise RuntimeError(f"磁盘空间不足：需要至少 8 GB，当前可用 {free / 1024**3:.1f} GB")

            env = self._env(source)
            if not (self.bin_dir / "python").exists():
                await self._run(
                    "创建 Python 环境",
                    uv, "venv", str(self.venv),
                    "--python", PYTHON_VERSION, "--python-preference", "only-managed",
                    env=env,
                )
            await self._run(
                "安装 MinerU",
                uv, "pip", "install", "--python", str(self.bin_dir / "python"), "-U", MINERU_REQUIREMENT,
                env=env,
            )
            self._write_config(source)
            kit = str(self.bin_dir / "mineru-kit")
            await self._run(
                f"下载模型 (tier={tier}, source={source})",
                kit, "models", "download", "--tier", tier, "--source", source,
                env=env,
            )
            await self._run("校验模型", kit, "models", "verify", "--tier", tier, env=env)

            version = await asyncio.to_thread(self._installed_version)
            self.state_path.write_text(json.dumps({
                "tier": tier,
                "source": source,
                "version": version,
                "installed_at": datetime.utcnow().isoformat(),
            }))
            self._install_step = "完成"
            self._log(f"MinerU {version} 已安装，模型已就绪 (tier={tier})")
            # A running server may be on the old tier/version
            await self.stop_server()
        except asyncio.CancelledError:
            self._install_step = "已取消"
            self._install_error = "安装已取消"
            self._log("安装已取消")
            raise
        except Exception as e:
            self._install_error = str(e)
            self._install_step = "失败"
            self._log(f"安装失败: {e}")
            logger.error("MinerU install failed: %s", e)
        finally:
            self._install_event.set()

    def _installed_version(self) -> str:
        try:
            out = subprocess.run(
                [str(self.bin_dir / "python"), "-c",
                 "import importlib.metadata as m; print(m.version('mineru'))"],
                capture_output=True, text=True, timeout=60, env=self._env(),
            )
            return out.stdout.strip() or "unknown"
        except (OSError, subprocess.SubprocessError):
            return "unknown"

    async def follow_install(self):
        """Yield ("log", line) for buffered + new lines, then ("done", status)."""
        sent = 0
        backlog = list(self._install_log)
        for line in backlog:
            yield "log", line
        sent = self._install_seq
        while True:
            if not self.install_running():
                # flush lines logged since the snapshot
                new = self._install_seq - sent
                if new > 0:
                    for line in list(self._install_log)[-new:]:
                        yield "log", line
                yield "done", {"error": self._install_error, "step": self._install_step}
                return
            self._install_event.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._install_event.wait(), timeout=15)
            new = self._install_seq - sent
            if new > 0:
                for line in list(self._install_log)[-min(new, LOG_TAIL):]:
                    yield "log", line
                sent = self._install_seq
            else:
                yield "ping", None

    async def uninstall(self) -> None:
        await self.cancel_install()
        await self.stop_server()
        await asyncio.to_thread(shutil.rmtree, self.root, True)
        self._install_log.clear()
        self._install_error = None
        self._install_step = ""

    # --- api-server --------------------------------------------------------------

    def _server_alive(self) -> bool:
        return self._server is not None and self._server.poll() is None

    def mark_busy(self, busy: bool) -> None:
        self._busy += 1 if busy else -1
        self._last_used = time.monotonic()

    def server_ready_for(self, tier: str, concurrency: int) -> bool:
        return (
            self._server_alive()
            and self._server_tier == tier
            and self._server_concurrency == concurrency
            and self._server_url is not None
        )

    async def ensure_server(self, tier: str, concurrency: int = 1) -> str:
        """Start (or reuse) the local api-server and return its base URL."""
        async with self._server_lock:
            if self.server_ready_for(tier, concurrency):
                self._last_used = time.monotonic()
                return self._server_url
            await self._stop_server_locked()

            port = _free_port()
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            kit = str(self.bin_dir / "mineru-kit")
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_file = open(self.log_path, "ab")
            try:
                self._server = subprocess.Popen(
                    [
                        kit, "api-server", "--host", "127.0.0.1", "--port", str(port),
                        "--tier", tier, "--concurrency", str(concurrency),
                        # MinerU locks its upload dir; keep it per data dir, not in the
                        # (possibly shared) install dir
                        "--upload-dir", str(UPLOAD_DIR),
                    ],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=self._env(self._state().get("source")),
                    cwd=str(self.root),
                    start_new_session=True,
                )
            finally:
                log_file.close()
            self.pid_path.write_text(str(self._server.pid))
            self._server_url = f"http://127.0.0.1:{port}"
            self._server_tier = tier
            self._server_concurrency = concurrency
            logger.info("Starting MinerU api-server pid=%s at %s", self._server.pid, self._server_url)

            deadline = time.monotonic() + SERVER_START_TIMEOUT
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                while time.monotonic() < deadline:
                    if self._server.poll() is not None:
                        tail = self._log_tail()
                        await self._stop_server_locked()
                        raise PipelineError("parse_error", f"本地 MinerU 服务启动失败:\n{tail}")
                    with contextlib.suppress(httpx.HTTPError):
                        response = await client.get(f"{self._server_url}/v1/health")
                        if response.status_code == 200:
                            break
                    await asyncio.sleep(1.0)
                else:
                    await self._stop_server_locked()
                    raise PipelineError("timeout", "本地 MinerU 服务启动超时")

            self._last_used = time.monotonic()
            if self._idle_task is None or self._idle_task.done():
                self._idle_task = asyncio.create_task(self._idle_watch())
            return self._server_url

    def _log_tail(self, lines: int = 15) -> str:
        try:
            content = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(content[-lines:])
        except OSError:
            return ""

    async def _idle_watch(self) -> None:
        while self._server_alive():
            await asyncio.sleep(30)
            if self._busy <= 0 and time.monotonic() - self._last_used > IDLE_SHUTDOWN:
                logger.info("MinerU api-server idle for %ds — stopping", IDLE_SHUTDOWN)
                await self.stop_server()
                return

    async def stop_server(self) -> None:
        async with self._server_lock:
            await self._stop_server_locked()

    async def _stop_server_locked(self) -> None:
        proc = self._server
        self._server = None
        self._server_url = None
        self._server_tier = None
        if proc is not None and proc.poll() is None:
            await asyncio.to_thread(self._terminate_group, proc.pid)
            with contextlib.suppress(Exception):
                await asyncio.to_thread(proc.wait, 5)
        self.pid_path.unlink(missing_ok=True)

    def kill_now(self, grace: float = 0.5) -> None:
        """App is quitting: stop the api-server and any install job right away.

        Lock-free (ensure_server may be holding the lock while models load) and with a
        short grace period — an inference server has no state worth a long wait.
        """
        proc, install = self._server, self._install_proc
        self._server = None
        self._server_url = None
        self._server_tier = None
        for running in (proc, install):
            pid = getattr(running, "pid", None)
            if pid is not None and running.returncode is None and (
                not isinstance(running, subprocess.Popen) or running.poll() is None
            ):
                self._terminate_group(pid, grace)
        self.pid_path.unlink(missing_ok=True)

    @staticmethod
    def _terminate_group(pid: int, grace: float = 5.0) -> None:
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGTERM)
        for _ in range(max(1, int(grace / 0.05))):
            time.sleep(0.05)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGKILL)

    def kill_stale_server(self) -> None:
        """Kill an api-server left behind by a crashed previous run."""
        try:
            pid = int(self.pid_path.read_text().strip())
        except (OSError, ValueError):
            return
        try:
            cmd = subprocess.run(
                ["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5
            ).stdout
        except (OSError, subprocess.SubprocessError):
            cmd = ""
        if "mineru" in cmd:
            logger.warning("Killing stale MinerU api-server pid=%s", pid)
            self._terminate_group(pid)
        self.pid_path.unlink(missing_ok=True)


_runtime: Optional[MineruRuntime] = None


def get_mineru_runtime() -> MineruRuntime:
    global _runtime
    if _runtime is None:
        _runtime = MineruRuntime()
    return _runtime
