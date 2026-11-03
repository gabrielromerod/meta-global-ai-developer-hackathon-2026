"""FIXTURE: uncertain post-send failures must reserve and charge the estimate."""

import httpx
import pytest
import respx

from tests.integration.test_client_faults import BASE, BODY, Env
from vigil.meta.client import MetaUnavailable, estimate_request


@pytest.mark.parametrize(
    ("error", "billed"),
    [(httpx.ConnectTimeout, False), (httpx.ReadTimeout, True), (httpx.WriteTimeout, True)],
)
@pytest.mark.parametrize("retries", [0, 2])
def test_client_timeout_billing(tmp_path, error, billed, retries):
    env = Env(tmp_path)
    with respx.mock as router, env.client(max_retries=retries) as client:
        router.post(BASE + "/responses").mock(side_effect=error("fixture timeout"))
        with pytest.raises(MetaUnavailable):
            client.responses("muse-spark-1.3", BODY, purpose="triage")
    row = env.ledger.rows()[0]
    cost = estimate_request("muse-spark-1.3", "triage", {**BODY, "model": "muse-spark-1.3"}).usd
    assert row.cost_usd == pytest.approx(cost * (retries + 1) if billed else 0)


class CutStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b'data: {"type":"response.output_text.delta","delta":"partial"}\n\n'
        raise httpx.ReadError("fixture cut after a partial stream")


def test_client_cut_stream_bills_estimate(tmp_path):
    env = Env(tmp_path)
    with respx.mock as router, env.client(max_retries=0) as client:
        router.post(BASE + "/responses").mock(
            return_value=httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=CutStream()
            )
        )
        with pytest.raises(MetaUnavailable):
            client.responses("muse-spark-1.3", BODY, purpose="triage", stream=True)
    assert env.ledger.rows()[0].cost_usd == pytest.approx(
        estimate_request(
            "muse-spark-1.3", "triage", {**BODY, "model": "muse-spark-1.3", "stream": True}
        ).usd
    )


def test_client_read_timeout_is_twenty_seconds(tmp_path):
    with Env(tmp_path).client() as client:
        assert client._http.timeout.read == 20
