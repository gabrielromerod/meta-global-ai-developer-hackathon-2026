"""The curated screenshots stay small without weakening their privacy checks."""

from scripts import scan_ui_evidence


def test_repo_images_must_stay_below_ten_megabytes(tmp_path):
    image = tmp_path / "web-next/public/image.svg"
    image.parent.mkdir(parents=True)
    with image.open("wb") as stream:
        stream.truncate(10_000_000)
    failures = scan_ui_evidence.image_budget_errors(tmp_path, ["web-next/public/image.svg"])
    assert any("10 MB" in failure for failure in failures)


def test_only_two_curated_qa_images_may_be_committed(tmp_path):
    paths = ["qa/final/home.png", "qa/final/visit.png", "qa/screens/extra.png"]
    for name in paths:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    assert scan_ui_evidence.image_budget_errors(tmp_path, paths[:2]) == []
    failures = scan_ui_evidence.image_budget_errors(tmp_path, paths)
    assert any("qa/screens/extra.png" in failure for failure in failures)


def test_image_budget_counts_assets_outside_qa(tmp_path):
    qa = tmp_path / "qa/final/home.png"
    qa.parent.mkdir(parents=True)
    qa.write_bytes(b"fixture")
    asset = tmp_path / "web-next/public/photo.jpg"
    asset.parent.mkdir(parents=True)
    with asset.open("wb") as stream:
        stream.truncate(9_999_999)
    failures = scan_ui_evidence.image_budget_errors(
        tmp_path, ["qa/final/home.png", "web-next/public/photo.jpg"]
    )
    assert any("10 MB" in failure for failure in failures)
