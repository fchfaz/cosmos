import pytest

from core.config import Settings
from core.context import Context
from core.main import create_app


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JARVIS_API_KEY", "testkey")
    for k in ("ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_ID", "IG_ACCESS_TOKEN", "IG_USER_ID"):
        monkeypatch.delenv(k, raising=False)


def make_settings(tmp_path, **extra):
    over = {"storage": {"db_path": str(tmp_path / "j.db")}, "llm": {"mode": "offline"},
            "email": {"token_path": str(tmp_path / "gmail_token.json")}, "notify": {"digest_hour": -1}}
    over.update(extra)
    return Settings.load(overrides=over)


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def ctx(settings):
    return Context(settings)


@pytest.fixture
def app(settings):
    return create_app(settings)
