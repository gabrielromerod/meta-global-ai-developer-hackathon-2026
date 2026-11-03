"""The reviewed React build owns both the root and preview alias."""

from fastapi.testclient import TestClient

from vigil.api.app import create_app
from vigil.settings import Settings


def test_react_build_is_served_at_root_and_preview_alias(tmp_path, monkeypatch):
    import vigil.api.app as module

    build = tmp_path / "dist"
    build.mkdir()
    (build / "index.html").write_text('<div id="react-review"></div>', encoding="utf-8")
    monkeypatch.setattr(module, "NEXT_WEB_DIR", build, raising=False)
    with TestClient(create_app(Settings(mode="sandbox", MODEL_API_KEY="invalid"))) as client:
        preview = client.get("/next/")
        assert preview.status_code == 200
        assert 'id="react-review"' in preview.text
        root = client.get("/")
        assert root.status_code == 200
        assert root.text == preview.text
        assert 'id="react-review"' in root.text
