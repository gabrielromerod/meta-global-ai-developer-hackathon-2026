"""Every tracked QA screenshot needs a valid scoped provenance manifest."""


def test_ui_tree_rejects_uncovered_tracked_images(tmp_path):
    from scripts.scan_ui_evidence import audit_tree

    image = tmp_path / "qa/screens/orphan.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"not reviewed")
    failures = audit_tree(tmp_path, ["qa/screens/orphan.png"])
    assert any("orphan.png" in failure and "manifest" in failure for failure in failures)


def test_ui_tree_does_not_treat_untracked_drafts_as_committed_assets(tmp_path):
    from scripts.scan_ui_evidence import audit_tree

    draft = tmp_path / "qa/draft.png"
    draft.parent.mkdir()
    draft.write_bytes(b"untracked draft")
    assert audit_tree(tmp_path, []) == []
