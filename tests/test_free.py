"""Free tier: no wallet needed for the first 10 checks."""

import json
import os
import stat

import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from provenpaid_mcp import identity
from provenpaid_mcp.client import ProvenPaidClient
from provenpaid_mcp.config import load_settings

URL = "https://api.example.com/x"


class FreeServer:
    """Mimics api.provenpaid.com/v1/free-check: verifies the EIP-191 signature, counts per wallet."""

    def __init__(self, limit=10, status_override=None):
        self.limit, self.used, self.status_override, self.paid_calls = limit, {}, status_override, 0

    def handler(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/check":
            self.paid_calls += 1
            return httpx.Response(402, json={"error": "payment required"})
        if self.status_override:
            return httpx.Response(self.status_override, json={"error": "free_daily_cap"})
        url = req.url.params["url"]
        addr, ts, sig = (req.headers[h] for h in ("x-provenpaid-address", "x-provenpaid-timestamp", "x-provenpaid-signature"))
        signer = Account.recover_message(encode_defunct(text=identity.message_for(url, int(ts))), signature=sig)
        assert signer.lower() == addr.lower()
        n = self.used.get(addr, 0)
        if n >= self.limit:
            return httpx.Response(402, json={"error": "free_quota_used"})
        self.used[addr] = n + 1
        return httpx.Response(200, json={"payer_depth": [], "free_tier": {"used": n + 1, "limit": self.limit,
                                                                           "remaining": self.limit - n - 1}})


def client(tmp_path, server, **env):
    s = load_settings({"PROVENPAID_STATE_DIR": str(tmp_path), **env})
    return ProvenPaidClient(s, transport=httpx.MockTransport(server.handler))


async def test_first_check_is_free_without_any_wallet(tmp_path):
    server = FreeServer()
    c = client(tmp_path, server)
    out = await c.check(URL)
    assert out["free_check"] and out["charged"] is False and out["free_checks_remaining"] == 9
    assert c.status()["free_checks_remaining"] == 9 and c.status()["ready_to_pay"] is False


async def test_identity_key_is_owner_only_and_reused(tmp_path):
    c1 = client(tmp_path, FreeServer())
    mode = stat.S_IMODE(os.stat(tmp_path / "identity.key").st_mode)
    assert mode == 0o600
    assert client(tmp_path, FreeServer()).identity.address == c1.identity.address


async def test_after_ten_free_checks_without_wallet_explains_how_to_continue(tmp_path):
    server = FreeServer(limit=2)
    c = client(tmp_path, server)
    assert (await c.check(URL))["free_check"] and (await c.check(URL))["free_check"]
    out = await c.check(URL)
    assert out["error"] == "wallet_not_configured" and "free checks" in out["detail"]
    assert json.loads((tmp_path / "free.json").read_text())["remaining"] == 0
    out2 = await c.check(URL)  # no more free-check calls once exhausted
    assert out2["error"] == "wallet_not_configured" and server.paid_calls == 0


async def test_daily_cap_falls_back_with_a_note(tmp_path):
    c = client(tmp_path, FreeServer(status_override=429))
    out = await c.check(URL)
    assert out["error"] == "wallet_not_configured" and out["free_unavailable"] == "free_daily_cap"


async def test_invalid_input_never_calls_the_server(tmp_path):
    server = FreeServer()
    out = await client(tmp_path, server).check("ftp://nope")
    assert out["error"] == "invalid_input" and server.used == {}
