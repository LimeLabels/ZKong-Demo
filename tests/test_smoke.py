"""Smoke test: app module imports and FastAPI app exists."""


def test_app_import():
    from app.main import app

    assert app is not None
