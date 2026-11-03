"""React build is served alongside the legacy app during review."""

from fastapi.testclient import TestClient

from vigil.api.app import create_app
from vigil.settings import Settings


def test_react_preview_keeps_current_app_available(tmp_path, monkeypatch):
    import vigil.api.app as module

    build = tmp_path / "dist"
    build.mkdir()
    (build / "index.html").write_text('<div id="react-review"></div>', encoding="utf-8")
    monkeypatch.setattr(module, "NEXT_WEB_DIR", build, raising=False)
    with TestClient(create_app(Settings(mode="sandbox", MODEL_API_KEY="invalid"))) as client:
        preview = client.get("/next/")
        assert preview.status_code == 200
        assert 'id="react-review"' in preview.text
        assert client.get("/").status_code == 200
