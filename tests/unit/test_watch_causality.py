"""FIXTURE: baseline tracks cannot acquire removal events from a future watch."""

from datetime import UTC, datetime, timedelta

import pytest

from vigil.models import Box, CameraCfg, Config, SamFrame, SamObject, Watch, Window
from vigil.pipeline import run_scenario


@pytest.mark.parametrize(("end_s", "removed"), [(100 + 86400, False), (86400, True), (3, False)])
def test_watch_temporal_eligibility_covers_events(end_s, removed):
    start = datetime(2026, 11, 3, tzinfo=UTC)
    window = Window(id="w", camera_id="front", t0=0, t1=10, width=1000, height=1000)
    box = Box(x1=200, y1=200, x2=300, y2=300)
    watch = Watch(
        id="car-watch",
        camera_id="front",
        phrase="car",
        origin="wonder",
        status="watching",
        expires_at=start + timedelta(seconds=end_s),
    )

    def source(w, phrase):
        times = [0, 4] if phrase == "car" else [0, 4, 10]
        return [
            SamObject(
                window_id=w.id,
                camera_id=w.camera_id,
                phrase=phrase,
                obj_id=0,
                frames=[SamFrame(frame=round(t * 10), t=t, box=box) for t in times],
            )
        ]

    result = run_scenario(
        {"windows": [window]},
        cfg=Config(cameras=[CameraCfg(id="front", name="Front")]),
        rules=[],
        protected=[],
        watches=[watch],
        session_start=start,
        sam=source,
    )
    assert any(e["type"] == "removed" for e in result["events"]) is removed
