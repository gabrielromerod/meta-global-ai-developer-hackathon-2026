"""FIXTURE: generated GLB loading and visible compression/size failures."""

import json

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import wait_ready
from tests.unit.test_glb_import import generated_glb

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize("compression", ["KHR_draco_mesh_compression", "EXT_meshopt_compression"])
def test_glb_compression_error_is_visible(page: Page, server_url, tmp_path, compression):
    data = generated_glb(tmp_path / "compressed.glb", compression).read_bytes()

    def twin(route):
        response = route.fetch()
        body = response.json()
        body["glb_url"] = "/fixture.glb"
        route.fulfill(response=response, body=json.dumps(body))

    page.route("**/api/twin", twin)
    page.route(
        "**/fixture.glb", lambda route: route.fulfill(body=data, content_type="model/gltf-binary")
    )
    page.goto(server_url)
    wait_ready(page)
    expect(page.get_by_test_id("glb-error")).to_contain_text("Draco/meshopt")
    expect(page.get_by_test_id("twin")).to_have_attribute("data-mode", "webgl")


def test_generated_glb_loads_in_viewer(page: Page, server_url, tmp_path):
    data = generated_glb(tmp_path / "generated.glb").read_bytes()

    def twin(route):
        response = route.fetch()
        body = response.json()
        body["glb_url"] = "/fixture.glb"
        route.fulfill(response=response, body=json.dumps(body))

    page.route("**/api/twin", twin)
    page.route(
        "**/fixture.glb", lambda route: route.fulfill(body=data, content_type="model/gltf-binary")
    )
    page.goto(server_url)
    wait_ready(page)
    expect(page.get_by_test_id("twin")).to_have_attribute("data-glb-loaded", "1")
