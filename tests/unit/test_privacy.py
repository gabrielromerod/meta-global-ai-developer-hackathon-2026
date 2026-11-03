"""FR-003, NFR-001, NFR-002: every pixel inside every privacy polygon is 0 in every output
frame, ffprobe finds no audio stream, and upload is refused otherwise."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from tests.fixtures.video.synth import blob_clip, texture_clip, write_video
from vigil.ingest.media import has_audio, probe
from vigil.ingest.privacy import (
    DEFAULT_MARGIN_PX,
    PrivacyViolation,
    assert_uploadable,
    mask_clip,
    mask_image,
    polygon_mask,
    scan_media,
    verify_clean,
)
from vigil.settings import ffmpeg_bin

REPO_ROOT = Path(__file__).resolve().parents[2]

# Polygons in a 1280x720 reference frame (the processed-window frame of cameras.yaml).
REF = (1280, 720)
POLYS = [
    [(0, 0), (1280, 0), (1280, 140), (0, 140)],  # street strip
    [(200, 300), (600, 360), (500, 640), (180, 600)],  # neighbour's window (irregular)
]


@pytest.fixture(scope="module")
def raw_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Bright moving texture everywhere, 640x360, with an audio track."""
    d = tmp_path_factory.mktemp("privacy")
    return texture_clip(d / "raw.mp4", 3.0, size=(640, 360), audio=True)


@pytest.fixture(scope="module")
def masked_clip(raw_clip: Path) -> Path:
    return mask_clip(raw_clip, raw_clip.with_name("masked.mp4"), POLYS, ref_size=REF)


def exact_inside(w: int, h: int) -> np.ndarray:
    return polygon_mask((w, h), POLYS, ref_size=REF)


def test_polygon_mask_scales_from_reference_frame() -> None:
    m = polygon_mask((640, 360), [[(0, 0), (1280, 0), (1280, 140), (0, 140)]], ref_size=REF)
    assert m.shape == (360, 640)
    assert m[:70].all()
    assert not m[72:].any()
    dilated = polygon_mask((640, 360), [[(0, 0), (640, 0), (640, 70), (0, 70)]], margin_px=5)
    assert dilated[:75].all()
    assert not dilated[77:].any()


def test_every_pixel_inside_polygons_is_zero_in_every_frame(masked_clip: Path) -> None:
    cap = cv2.VideoCapture(str(masked_clip))
    inside = exact_inside(640, 360)
    frames = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames += 1
        assert int(frame[inside].max()) == 0, f"frame {frames - 1} leaks inside a polygon"
        # The rest of the picture survives (masking is not "black everything").
        assert frame[~polygon_mask((640, 360), POLYS, ref_size=REF, margin_px=20)].mean() > 60
    cap.release()
    assert frames == 30


def test_masked_clip_has_no_audio_stream(raw_clip: Path, masked_clip: Path) -> None:
    assert has_audio(raw_clip)
    assert not has_audio(masked_clip)
    info = probe(masked_clip)
    assert info.audio_streams == 0
    assert (info.width, info.height) == (640, 360)


def test_verify_clean_accepts_masked_rejects_raw(raw_clip: Path, masked_clip: Path) -> None:
    assert verify_clean(masked_clip, POLYS, ref_size=REF)
    assert not verify_clean(raw_clip, POLYS, ref_size=REF)
    rep = scan_media(raw_clip, POLYS, ref_size=REF)
    assert rep.nonzero_pixels > 0
    assert rep.first_bad_frame == 0
    assert rep.audio_streams == 1
    assert not rep.ok
    assert any("audio" in r for r in rep.reasons)


def test_audio_alone_fails_verification(masked_clip: Path, tmp_path: Path) -> None:
    with_audio = tmp_path / "masked_plus_audio.mp4"
    subprocess.run(
        [ffmpeg_bin(), "-v", "error", "-y", "-i", str(masked_clip), "-f", "lavfi", "-i",
         "sine=frequency=440:duration=3", "-c:v", "copy", "-c:a", "aac", "-shortest",
         str(with_audio)],
        check=True,
    )  # fmt: skip
    rep = scan_media(with_audio, POLYS, ref_size=REF)
    assert rep.nonzero_pixels == 0
    assert rep.audio_streams == 1
    assert not verify_clean(with_audio, POLYS, ref_size=REF)


def test_assert_uploadable_refuses_unmasked(raw_clip: Path, masked_clip: Path) -> None:
    with pytest.raises(PrivacyViolation) as ei:
        assert_uploadable(raw_clip, POLYS, ref_size=REF)
    assert ei.value.report.nonzero_pixels > 0
    rep = assert_uploadable(masked_clip, POLYS, ref_size=REF)
    assert rep.ok
    assert rep.frames == 30


def test_assert_uploadable_refuses_unreadable(tmp_path: Path) -> None:
    bogus = tmp_path / "broken.mp4"
    bogus.write_bytes(b"not a video")
    with pytest.raises(PrivacyViolation):
        assert_uploadable(bogus, POLYS, ref_size=REF)


def test_masking_is_exact_at_high_compression(raw_clip: Path, tmp_path: Path) -> None:
    """Lossy re-encode must not bleed into the exact polygon (super-black + margin design)."""
    out = mask_clip(raw_clip, tmp_path / "crf40.mp4", POLYS, ref_size=REF, crf=40)
    assert verify_clean(out, POLYS, ref_size=REF)
    assert DEFAULT_MARGIN_PX >= 8


def test_mask_clip_strips_container_metadata(tmp_path: Path) -> None:
    src = blob_clip(tmp_path / "plain.mp4", 1.0, size=(320, 180))
    tagged = tmp_path / "tagged.mp4"
    subprocess.run(
        [ffmpeg_bin(), "-v", "error", "-y", "-i", str(src), "-c", "copy",
         "-metadata", "title=synthetic-secret", "-metadata", "comment=device-xyz",
         str(tagged)],
        check=True,
    )  # fmt: skip
    assert "synthetic-secret" in str(probe(tagged).tags)
    out = mask_clip(tagged, tmp_path / "clean.mp4", [])
    tags = probe(out).tags
    assert "synthetic-secret" not in str(tags)
    assert "device-xyz" not in str(tags)


def test_mask_clip_odd_dimensions(tmp_path: Path) -> None:
    def frame(i: int) -> np.ndarray:
        return np.full((181, 321, 3), 200, np.uint8)

    src = write_video(tmp_path / "odd.mp4", frame, 10, 10.0, (321, 181), pix_fmt="yuv444p")
    out = mask_clip(src, tmp_path / "odd_masked.mp4", [[(0, 0), (100, 0), (100, 100)]])
    info = probe(out)
    assert info.width % 2 == 0
    assert info.height % 2 == 0
    assert verify_clean(out, [[(0, 0), (100, 0), (100, 100)]], ref_size=(321, 181))


@pytest.mark.parametrize("ext", [".png", ".jpg"])
def test_mask_image(tmp_path: Path, ext: str) -> None:
    rng = np.random.default_rng(3)
    img = rng.integers(0, 256, size=(360, 640, 3), dtype=np.uint8)
    src = tmp_path / f"still{ext}"
    cv2.imwrite(str(src), img)
    assert not verify_clean(src, POLYS, ref_size=REF)
    out = mask_image(src, tmp_path / f"still_masked{ext}", POLYS, ref_size=REF)
    rep = scan_media(out, POLYS, ref_size=REF)
    assert rep.kind == "image"
    assert rep.ok, rep.reasons


def test_no_polygons_still_checks_audio(raw_clip: Path, masked_clip: Path) -> None:
    assert verify_clean(masked_clip, [])
    assert not verify_clean(raw_clip, [])


# ---------------------------------------------------------------------------
# scripts/privacy_scan.py (NFR-001, NFR-002)
# ---------------------------------------------------------------------------

SCAN_CFG = """\
cameras:
  - id: front
    name: Front
    width: 640
    height: 360
    privacy:
      - [[0, 0], [640, 0], [640, 70], [0, 70]]
  - id: backyard
    name: Backyard
    width: 640
    height: 360
"""
FRONT_POLYS = [[(0, 0), (640, 0), (640, 70), (0, 70)]]


def run_scan(root: Path, cfg: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "privacy_scan.py"), str(root),
         "--config", str(cfg), "--privacy-dir", str(cfg.parent / "privacy"), *extra],
        capture_output=True, text=True, timeout=120, cwd=REPO_ROOT,
    )  # fmt: skip


@pytest.fixture
def scan_cfg(tmp_path: Path) -> Path:
    p = tmp_path / "cfg" / "cameras.yaml"
    p.parent.mkdir()
    p.write_text(SCAN_CFG, encoding="utf-8")
    return p


def test_privacy_scan_missing_and_empty_dir_pass(tmp_path: Path, scan_cfg: Path) -> None:
    r = run_scan(tmp_path / "does_not_exist", scan_cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    empty = tmp_path / "demo"
    (empty / "C").mkdir(parents=True)
    (empty / "C" / "visits.json").write_text("{}", encoding="utf-8")
    r = run_scan(empty, scan_cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 media files" in r.stdout


def test_privacy_scan_passes_masked_and_fails_unmasked(tmp_path: Path, scan_cfg: Path) -> None:
    demo = tmp_path / "demo"
    raw = blob_clip(tmp_path / "raw.mp4", 1.0, size=(640, 360))
    mask_clip(raw, demo / "C" / "front" / "w000.mp4", FRONT_POLYS)
    mask_clip(raw, demo / "C" / "backyard_w000.mp4", [])
    r = run_scan(demo, scan_cfg)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 media files" in r.stdout

    shutil.copy(raw, demo / "C" / "front" / "w001.mp4")  # unmasked
    r = run_scan(demo, scan_cfg)
    assert r.returncode == 1
    assert "w001.mp4" in r.stdout


def test_privacy_scan_fails_on_audio(tmp_path: Path, scan_cfg: Path) -> None:
    demo = tmp_path / "demo"
    texture_clip(demo / "backyard" / "clip.mp4", 1.0, size=(320, 180), audio=True)
    r = run_scan(demo, scan_cfg)
    assert r.returncode == 1
    assert "audio" in r.stdout


def test_privacy_scan_fails_on_unmapped_media(tmp_path: Path, scan_cfg: Path) -> None:
    demo = tmp_path / "demo"
    (demo / "misc").mkdir(parents=True)
    cv2.imwrite(str(demo / "misc" / "poster.png"), np.zeros((10, 10, 3), np.uint8))
    r = run_scan(demo, scan_cfg)
    assert r.returncode == 1
    assert "no camera" in r.stdout
    r = run_scan(demo, scan_cfg, "--allow-unmapped")
    assert r.returncode == 0, r.stdout + r.stderr


def test_privacy_scan_privacy_json_applies(tmp_path: Path, scan_cfg: Path) -> None:
    pdir = scan_cfg.parent / "privacy"
    pdir.mkdir()
    (pdir / "backyard.json").write_text(
        '{"camera_id": "backyard", "polygons": [[[0, 0], [100, 0], [100, 100], [0, 100]]]}',
        encoding="utf-8",
    )
    demo = tmp_path / "demo"
    (demo / "backyard").mkdir(parents=True)
    raw = blob_clip(tmp_path / "raw.mp4", 1.0, size=(640, 360))
    shutil.copy(raw, demo / "backyard" / "a.mp4")
    r = run_scan(demo, scan_cfg)
    assert r.returncode == 1  # the JSON polygon covers non-black pixels
    mask_clip(raw, demo / "backyard" / "a.mp4", [[(0, 0), (100, 0), (100, 100), (0, 100)]])
    r = run_scan(demo, scan_cfg)
    assert r.returncode == 0, r.stdout + r.stderr


# ---------------------------------------------------------------------------
# scripts/metadata_scan.sh (NFR-032)
# ---------------------------------------------------------------------------


def _git_bash() -> str | None:
    """A POSIX bash that understands this OS's paths (never WSL's System32 bash)."""
    for cand in (shutil.which("bash"), r"C:\Program Files\Git\usr\bin\bash.exe",
                 r"C:\Program Files\Git\bin\bash.exe"):  # fmt: skip
        if cand and Path(cand).exists() and "system32" not in cand.lower():
            if "windowsapps" in cand.lower():
                continue
            return cand
    return None


BASH = _git_bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="no POSIX bash available")


def run_meta(root: Path, exiftool: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, EXIFTOOL=exiftool)
    if BASH:
        # Put the chosen bash's folder first so `#!/usr/bin/env bash` in the fake exiftool
        # (and sed in the script) resolve there, not to the WSL stub in System32 when pytest
        # starts from PowerShell or cmd.
        env["PATH"] = str(Path(BASH).parent) + os.pathsep + env.get("PATH", "")
    script = (REPO_ROOT / "scripts" / "metadata_scan.sh").as_posix()
    return subprocess.run(
        [BASH or "bash", script, root.as_posix()],
        capture_output=True, text=True, timeout=60, env=env,
    )  # fmt: skip


@needs_bash
def test_metadata_scan_skips_without_exiftool(tmp_path: Path) -> None:
    r = run_meta(tmp_path, "definitely-not-exiftool-xyz")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "exiftool not found" in (r.stdout + r.stderr)


@needs_bash
def test_metadata_scan_missing_dir_passes(tmp_path: Path) -> None:
    r = run_meta(tmp_path / "nope", "definitely-not-exiftool-xyz")
    assert r.returncode == 0


def _fake_exiftool(tmp_path: Path, gps: str, device: str) -> str:
    """A stand-in exiftool: prints canned lines for GPS / device queries."""
    fake = tmp_path / "fake_exiftool"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        f'  *GPS*) printf "%s" "{gps}" ;;\n'
        f'  *Make*) printf "%s" "{device}" ;;\n'
        "esac\n"
        "exit 0\n",
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o755)
    return fake.as_posix()


@needs_bash
def test_metadata_scan_fails_on_gps(tmp_path: Path) -> None:
    (tmp_path / "demo").mkdir()
    fake = _fake_exiftool(tmp_path, "demo/scan.jpg\\n", "")
    r = run_meta(tmp_path / "demo", fake)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "GPS" in r.stdout


@needs_bash
def test_metadata_scan_fails_on_device_metadata(tmp_path: Path) -> None:
    (tmp_path / "demo").mkdir()
    fake = _fake_exiftool(tmp_path, "", "demo/still.jpg: Apple iPhone\\n")
    r = run_meta(tmp_path / "demo", fake)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "device" in r.stdout.lower()


@needs_bash
def test_metadata_scan_clean(tmp_path: Path) -> None:
    (tmp_path / "demo").mkdir()
    fake = _fake_exiftool(tmp_path, "", "")
    r = run_meta(tmp_path / "demo", fake)
    assert r.returncode == 0, r.stdout + r.stderr
