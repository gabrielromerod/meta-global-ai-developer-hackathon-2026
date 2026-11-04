"""FIXTURE: public React renderer refuses identifying GLB assets, including valid/compressed ones.

The new privacy requirement supersedes the legacy public imported-GLB display. Local GLB
import, compression validation and coordinate transforms remain covered by unchanged
backend tests. These browser cases strengthen the public boundary to zero asset requests.
"""

import json

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import wait_ready
from tests.unit.test_glb_import import generated_glb

pytestmark = pytest.mark.e2e


def _public_boundary(page: Page, server_url: str, data: bytes):
    requests = []
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "request",
        lambda request: (
            requests.append(request.url) if request.url.endswith("/fixture.glb") else None
        ),
    )

    def twin(route):
        response = route.fetch()
        body = response.json()
        body["glb_url"] = "/fixture.glb"
        route.fulfill(response=response, body=json.dumps(body))

    page.route("**/api/ui/twin", twin)
    page.route(
        "**/fixture.glb", lambda route: route.fulfill(body=data, content_type="model/gltf-binary")
    )
    with page.expect_response("**/api/ui/twin"):
        page.goto(server_url + "/next/")
    wait_ready(page)
    expect(page.locator(".house-view canvas")).to_be_visible()
    page.wait_for_function("document.querySelector('[data-testid=twin-canvas]')?.dataset.cameraY")
    expect(
        page.get_by_text("Stylized property · approximate locations", exact=True)
    ).to_be_visible()
    # The live-alert EventSource stays open, so "networkidle" never fires; give any
    # deferred asset loader a bounded window instead.
    page.wait_for_timeout(1500)
    assert requests == [], "Public house view must never fetch a private GLB"
    assert not errors, errors


@pytest.mark.parametrize("compression", ["KHR_draco_mesh_compression", "EXT_meshopt_compression"])
def test_public_viewer_never_fetches_private_compressed_glb(
    page, server_url, tmp_path, compression
):
    data = generated_glb(tmp_path / "compressed.glb", compression).read_bytes()
    _public_boundary(page, server_url, data)


def test_public_viewer_uses_generic_massing_instead_of_private_generated_glb(
    page, server_url, tmp_path
):
    data = generated_glb(tmp_path / "generated.glb").read_bytes()
    assert data.startswith(b"glTF")
    _public_boundary(page, server_url, data)
