"""FIXTURE contract tests of smoke probes; never execute the live script entry point."""

import json

import httpx
import pytest
import respx

from scripts import smoke_meta
from tests.fixtures.video.synth import blob_clip
from tests.integration.test_client_faults import BASE, Env
from vigil.meta.asr import parse_transcript
from vigil.meta.wonder import assert_no_media


@pytest.mark.parametrize("model", ["muse-spark-1.3", "muse-wonder-1.0"])
def test_smoke_text_format_strict_schema(model):
    body = smoke_meta.request_body(model)
    fmt = body.get("text", {}).get("format", {})
    assert fmt.get("type") == "json_schema"
    assert fmt["strict"] is True
    assert fmt["schema"]["additionalProperties"] is False
    assert_no_media(smoke_meta.request_body("muse-wonder-1.0"))


def test_smoke_video_upload_and_real_voice_adapter_with_http_fixtures(tmp_path):
    probe = getattr(smoke_meta, "run_probe", None)
    assert callable(probe), "smoke probes must exercise upload and multipart voice"
    env = Env(tmp_path)
    video = blob_clip(tmp_path / "synthetic.mp4", 0.5, size=(160, 90))
    with respx.mock as router, env.client() as client:
        upload = router.post(BASE + "/files").mock(
            return_value=httpx.Response(200, json={"id": "file_test_001"})
        )

        def respond(request):
            if json.loads(request.content)["model"] == "sam-3.1":
                event = {
                    "type": "response.completed",
                    "response": {"status": "completed", "output_text": ""},
                }
                return httpx.Response(200, text="data: " + json.dumps(event) + "\n\n")
            return httpx.Response(200, json={"status": "completed", "output_text": '{"ok": true}'})

        response = router.post(BASE + "/responses").mock(side_effect=respond)
        probe(client, "sam-3.1", video)
        body = json.loads(response.calls[-1].request.content)
        assert body["input"][0]["content"][1] == {"type": "input_video", "file_id": "file_test_001"}
        assert upload.call_count == 1
        probe(client, "muse-spark-1.3", video)
        body = json.loads(response.calls[-1].request.content)
        assert any(p["type"] == "input_video" for p in body["input"][0]["content"])
        assert body["text"]["format"]["strict"] is True
        voice = router.post(BASE + "/asr/transcribe").mock(
            return_value=httpx.Response(200, json={"turns": [{"transcript": "synthetic voice"}]})
        )
        raw = probe(client, "muse-voice-transcribe-1.0", None)
        assert parse_transcript(raw) == "synthetic voice"
        assert b'name="audio"' in voice.calls[0].request.content
        assert b"RIFF" in voice.calls[0].request.content
    assert env.ledger.rows()[-1].model == "muse-voice-transcribe-1.0"
