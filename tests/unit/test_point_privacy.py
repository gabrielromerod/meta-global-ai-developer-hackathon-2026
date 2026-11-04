"""FR-019/003: inline point-prompt pixels have the same fail-closed guard as video."""

import cv2
import numpy as np
import pytest


def test_point_prompt_requires_explicit_privacy_context(tmp_path):
    from vigil.ingest.privacy import PrivacyViolation
    from vigil.meta.sam import segment_point

    image = tmp_path / "generated.png"
    assert cv2.imwrite(str(image), np.zeros((24, 24, 3), dtype=np.uint8))

    class NoModel:
        def responses(self, *args, **kwargs):
            raise AssertionError("pixels reached model without privacy context")

    with pytest.raises(PrivacyViolation):
        segment_point(NoModel(), image, 10, 10)


def test_point_backend_rejects_unreviewed_real_camera_before_model(tmp_path, monkeypatch):
    from vigil.api.backend import MetaLiveBackend
    from vigil.settings import Settings

    stills = tmp_path / "stills"
    stills.mkdir()
    # side_left is never owner-reviewed in the real config (the front Duos are, Nov 3).
    assert cv2.imwrite(str(stills / "side_left.jpg"), np.zeros((720, 1280, 3), dtype=np.uint8))
    backend = MetaLiveBackend(
        Settings(
            _env_file=None,
            MODEL_API_KEY="invalid",
            meta_cache_only=True,
            meta_base_url="http://127.0.0.1:9/v1",
        ),
        stills,
    )

    def no_client():
        raise AssertionError("unreviewed point reached client construction")

    monkeypatch.setattr(backend, "_meta_client", no_client)
    with pytest.raises(ValueError, match="owner privacy review"):
        backend.protect("side_left", None, 600, 400, "generated object")
    assert backend._client is None


def test_point_backend_scales_full_reference_and_returns_box_contract(
    tmp_path, monkeypatch, sample_config
):
    import json
    from types import SimpleNamespace

    from vigil.api.backend import MetaLiveBackend
    from vigil.meta import sam
    from vigil.models import Box
    from vigil.settings import Settings

    config = tmp_path / "cameras.yaml"
    config.write_text(json.dumps(sample_config.model_dump(mode="json", by_alias=True)))
    stills = tmp_path / "stills"
    stills.mkdir()
    assert cv2.imwrite(str(stills / "side_left.jpg"), np.zeros((180, 320, 3), dtype=np.uint8))

    def point(client, still, x, y, **privacy):
        assert (x, y) == (210, 125)
        assert privacy["ref_size"] == (1280, 720)
        assert privacy["polygons"]
        return sam.PointMask(
            obj_id=1, box=Box(x1=200, y1=100, x2=240, y2=160), mask_rle="0", width=320, height=180
        )

    monkeypatch.setattr(sam, "segment_point", point)
    backend = MetaLiveBackend(
        Settings(_env_file=None, config_path=config, meta_cache_only=True), stills
    )
    backend._client = SimpleNamespace(ledger=[])
    result = backend.protect("side_left", None, 840, 500, "gate")
    assert result.payload["mask"]["bbox"] == {"x1": 800, "y1": 400, "x2": 960, "y2": 640}
