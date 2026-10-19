"""Test setup: an isolated data dir must be configured before `app` is imported."""

import os
import tempfile

_DATA_DIR = tempfile.mkdtemp(prefix="paper-insight-test-")
os.environ["PAPER_INSIGHT_DATA_DIR"] = _DATA_DIR

import pytest  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from app.config import ensure_dirs  # noqa: E402
from app.database import engine  # noqa: E402
import app.models  # noqa: E402,F401


@pytest.fixture(autouse=True)
def fresh_db():
    ensure_dirs()
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    # base_url must be a local host: the LocalOnly middleware rejects anything else
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c
