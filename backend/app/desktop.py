"""PaperInsight desktop entry point: local API server + native macOS window.

The FastAPI app (API + built Vue UI) runs in a background thread on 127.0.0.1 and a
pywebview (WKWebView) window shows it. Closing the window shuts the server down, which
stops the scheduler and any MinerU server the app started.

Dev:      cd backend && uv run python -m app.desktop
Packaged: packaging/PaperInsight.spec (see scripts/build_mac.sh)
"""

import contextlib
import fcntl
import html
import os
import socket
import threading
import time
import urllib.request

PREFERRED_PORT = 41765  # a stable port keeps the WebView origin (and its storage) stable
STARTUP_TIMEOUT = 60


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Like uvicorn's own bind: a port in TIME_WAIT (right after a quit) is usable
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _pick_port() -> int:
    if _port_free(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _acquire_instance_lock(data_dir):
    """Hold an exclusive lock for the app's lifetime; None if another instance has it."""
    lock_file = open(data_dir / ".instance.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def _wait_until_healthy(port: int, server, thread: threading.Thread) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    url = f"http://127.0.0.1:{port}/api/health"
    while time.monotonic() < deadline:
        if not thread.is_alive():
            return False
        if server.started:
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return True
            except OSError:
                pass
        time.sleep(0.1)
    return False


def _error_page(message: str, log_path) -> str:
    try:
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:])
    except OSError:
        tail = ""
    return (
        "<html><body style='font-family:-apple-system,sans-serif;padding:32px;color:#0f1419'>"
        f"<h2>PaperInsight 启动失败</h2><p>{html.escape(message)}</p>"
        f"<p style='color:#8899a6'>日志：{html.escape(str(log_path))}</p>"
        "<pre style='background:#f5f4f2;padding:12px;border-radius:8px;font-size:11px;"
        f"white-space:pre-wrap'>{html.escape(tail)}</pre></body></html>"
    )


def main() -> None:
    from app.config import APP_NAME, DATA_DIR, LOG_DIR, ensure_dirs

    ensure_dirs()
    lock = _acquire_instance_lock(DATA_DIR)

    import webview

    if lock is None:
        webview.create_window(
            APP_NAME, html=_error_page("PaperInsight 已在运行。", LOG_DIR / "app.log"), width=520, height=260
        )
        webview.start()
        return

    import uvicorn

    from app.logging_config import get_logger
    from app.main import app

    logger = get_logger("desktop")
    port = _pick_port()
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_config=None,          # app.logging_config already set up handlers
        access_log=False,
        timeout_graceful_shutdown=0.5,  # quitting cancels open streams (analyses resume later)
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()
    logger.info("Desktop app starting on http://127.0.0.1:%d (data: %s)", port, DATA_DIR)

    stopped = threading.Event()

    def shutdown() -> None:
        """Stop the server (scheduler, MinerU via lifespan). Idempotent; well under 1s."""
        if stopped.is_set():
            return
        stopped.set()
        started = time.monotonic()
        logger.info("Shutting down")
        server.should_exit = True
        thread.join(timeout=2.5)
        if thread.is_alive():
            server.force_exit = True
            thread.join(timeout=1)
        # Lifespan shutdown normally stops it; make sure no MinerU process outlives the app
        from app.services.mineru_runtime import get_mineru_runtime

        get_mineru_runtime().kill_now()
        logger.info("Shutdown took %.2fs", time.monotonic() - started)

    def on_closing() -> None:
        """Close button, Cmd+Q and macOS logout all land here, on the main thread, before
        the app terminates. Hide the window first so quitting feels instant, then clean
        up (~0.2s idle, <1s with open requests) and let the quit proceed — never cancel
        it, or macOS would report that the app interrupted logout/restart."""
        native = getattr(window, "native", None)
        if native is not None:
            with contextlib.suppress(Exception):
                native.orderOut_(None)
        shutdown()

    if _wait_until_healthy(port, server, thread):
        window = webview.create_window(
            APP_NAME,
            f"http://127.0.0.1:{port}/",
            width=1360,
            height=900,
            min_size=(960, 640),
            text_select=True,
        )
    else:
        logger.error("Local server failed to start")
        window = webview.create_window(
            APP_NAME, html=_error_page("本地服务未能启动。", LOG_DIR / "app.log"), width=760, height=560
        )
    # `closing` runs synchronously on the main thread for both the close button and Cmd+Q
    window.events.closing += on_closing

    # Blocks until the window is closed (pywebview must own the main thread on macOS)
    webview.start(private_mode=False, storage_path=str(DATA_DIR / "webview"))

    shutdown()
    lock.close()
    # Daemon threads (scheduler executors, httpx pools) must not keep the process alive
    os._exit(0)


if __name__ == "__main__":
    main()
