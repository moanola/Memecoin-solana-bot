import os
import sys

# Dummy env so importing the bot never needs real credentials. No network is
# used: tests never start polling and monkeypatch every network call they hit.
os.environ.setdefault("BOT_TOKEN", "123456:TEST-DUMMY-TOKEN")
os.environ.setdefault("ACCESS_CONTROL_ENABLED", "true")
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_KEY", None)
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("HELIUS_API_KEY", None)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated_sqlite(monkeypatch, tmp_path):
    """Point SQLite persistence at a temp file so tests never touch real data."""
    import persistence
    monkeypatch.setattr(persistence, "DB_PATH", str(tmp_path / "test.db"), raising=False)
    yield
