"""End-to-end against a real x402 SDK paywall (fake facilitator, no network, no funds)."""

import json
import secrets
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from x402.schemas import SettleResponse, SupportedKind, SupportedResponse, VerifyResponse

from provenpaid_mcp.client import ProvenPaidClient
from provenpaid_mcp.config import MAINNET, TESTNET, ConfigError, load_settings

PAY_TO = "0x528ea612C35c1d77eEf259A3e5FD7903fed3c42c"


class FakeFacilitator:
    def __init__(self, network):
        self.network, self.settled = network, []

    def get_supported(self):
        return SupportedResponse(kinds=[SupportedKind(x402_version=2, scheme="exact", network=self.network)])

    async def verify(self, payload, requirements):
        return VerifyResponse(is_valid=True, payer=payload.payload["authorization"]["from"])

    async def settle(self, payload, requirements):
        self.settled.append(payload)
        return SettleResponse(success=True, transaction="0x" + "ab" * 32, network=self.network,
                              payer=payload.payload["authorization"]["from"])


def provenpaid_app(price="$0.01", network=MAINNET, status=200):
    from x402 import x402ResourceServer
    from x402.http.middleware import PaymentMiddlewareASGI
    from x402.mechanisms.evm.exact import ExactEvmServerScheme

    fac = FakeFacilitator(network)
    app = FastAPI()

    @app.get("/v1/check")
    async def check(url: str):
        if status != 200:
            return JSONResponse({"error": "not_x402", "detail": "no challenge", "charged": False}, status_code=status)
        return {"url": url, "probe": {"valid": True}, "onchain": [{"status": "ok"}]}

    @app.get("/methodology", response_class=PlainTextResponse)
    async def methodology():
        return "# ProvenPaid methodology"

    server = x402ResourceServer(fac)
    server.register("eip155:*", ExactEvmServerScheme())
    app.add_middleware(PaymentMiddlewareASGI, routes={"GET /v1/check": {
        "accepts": {"scheme": "exact", "payTo": PAY_TO, "price": price, "network": network}}}, server=server)
    return app, fac


def make_client(tmp_path, app, **env):
    key = "0x" + secrets.token_hex(32)
    base = {"PROVENPAID_WALLET_PRIVATE_KEY": key, "PROVENPAID_STATE_DIR": str(tmp_path),
            "PROVENPAID_API_URL": "https://api.provenpaid.test"}
    settings = load_settings({**base, **env})
    return ProvenPaidClient(settings, transport=httpx.ASGITransport(app=app)), key


async def test_paid_check_pays_once_and_returns_report(tmp_path):
    app, fac = provenpaid_app()
    client, key = make_client(tmp_path, app)
    out = await client.check("https://seller.example/x")
    assert out["charged"] is True and out["report"]["onchain"][0]["status"] == "ok"
    assert len(fac.settled) == 1
    auth = fac.settled[0].payload["authorization"]
    assert auth["to"].lower() == PAY_TO.lower() and int(auth["value"]) == 10_000
    assert client.budget.used_today() == 1


async def test_refuses_price_above_cap_without_signing(tmp_path):
    app, fac = provenpaid_app(price="$0.05")
    client, _ = make_client(tmp_path, app)
    out = await client.check("https://seller.example/x")
    assert out == {**out, "charged": False, "error": "price_or_network_refused"}
    assert fac.settled == [] and client.budget.used_today() == 0


async def test_refuses_wrong_network(tmp_path):
    app, fac = provenpaid_app(network=TESTNET)
    client, _ = make_client(tmp_path, app)  # configured for mainnet
    out = await client.check("https://seller.example/x")
    assert out["charged"] is False and out["error"] == "price_or_network_refused" and fac.settled == []


async def test_daily_limit_stops_payment(tmp_path):
    app, fac = provenpaid_app()
    client, _ = make_client(tmp_path, app, PROVENPAID_DAILY_LIMIT="1")
    assert (await client.check("https://a.example/x"))["charged"] is True
    second = await client.check("https://b.example/x")
    assert second["charged"] is False and second["error"] == "budget" and len(fac.settled) == 1
    again = ProvenPaidClient(client.settings, transport=httpx.ASGITransport(app=app))  # restart keeps the count
    assert (await again.check("https://c.example/x"))["error"] == "budget"


async def test_uncharged_server_outcome_is_reported(tmp_path):
    app, fac = provenpaid_app(status=422)
    client, _ = make_client(tmp_path, app)
    out = await client.check("https://not-x402.example/")
    assert out["charged"] is False and out["status"] == 422 and out["error"] == "not_x402"
    assert fac.settled == []  # the SDK does not settle on 4xx


async def test_no_wallet_means_no_payment(tmp_path):
    app, fac = provenpaid_app()
    settings = load_settings({"PROVENPAID_STATE_DIR": str(tmp_path), "PROVENPAID_API_URL": "https://api.provenpaid.test"})
    client = ProvenPaidClient(settings, transport=httpx.ASGITransport(app=app))
    out = await client.check("https://seller.example/x")
    assert out["error"] == "wallet_not_configured" and fac.settled == []
    assert "# ProvenPaid methodology" in await client.methodology()


async def test_invalid_input_is_not_sent(tmp_path):
    app, fac = provenpaid_app()
    client, _ = make_client(tmp_path, app)
    for bad in ("", "ftp://x", "not a url", "x" * 3000):
        assert (await client.check(bad))["error"] == "invalid_input"
    assert fac.settled == []


async def test_private_key_never_exposed(tmp_path):
    app, _ = provenpaid_app()
    client, key = make_client(tmp_path, app)
    blob = json.dumps(client.status()) + repr(client.settings) + Path(tmp_path).joinpath("usage.json").read_text() \
        if Path(tmp_path).joinpath("usage.json").exists() else json.dumps(client.status()) + repr(client.settings)
    assert key[2:] not in blob and key not in blob
    assert client.status()["paying_wallet"].startswith("0x")


@pytest.mark.parametrize("env,msg", [
    ({"PROVENPAID_API_URL": "http://api.provenpaid.com"}, "https"),
    ({"PROVENPAID_NETWORK": "eip155:1"}, "PROVENPAID_NETWORK"),
    ({"PROVENPAID_MAX_PRICE_USD": "0.50"}, "at most"),
    ({"PROVENPAID_MAX_PRICE_USD": "0"}, "above 0"),
    ({"PROVENPAID_DAILY_LIMIT": "0"}, "between"),
    ({"PROVENPAID_WALLET_PRIVATE_KEY": "my seed words"}, "private key"),
])
def test_config_fails_closed(env, msg):
    with pytest.raises(ConfigError, match=msg):
        load_settings(env)
