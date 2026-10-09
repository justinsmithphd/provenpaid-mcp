"""Calls the ProvenPaid API, paying over x402 when a check costs money.

Payment uses the official x402 SDK (x402==2.8.0): an x402Client with the exact EVM scheme and
an eth_account signer. Guardrails, all enforced before anything is signed:
- only the configured network (Base by default) and only its USDC contract;
- never more than PROVENPAID_MAX_PRICE_USD per check (hard ceiling $0.10);
- never more than PROVENPAID_DAILY_LIMIT paid checks per UTC day;
- at most one payment attempt per request (the SDK does not retry a payment).
The private key is held only in memory and never logged or returned.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx

from .budget import DailyBudget
from .config import USDC, Settings

TIMEOUT_S = 90.0  # a check can take up to ~70 s server side
USER_AGENT = "provenpaid-mcp/0.1"


def _guard_policy(settings: Settings):
    asset = USDC[settings.network].lower()

    def policy(version: int, reqs: list) -> list:
        return [
            r for r in reqs
            if r.network == settings.network  # PaymentRequirementsView properties (x402==2.8.0)
            and str(r.asset).lower() == asset
            and int(r.get_amount()) <= settings.max_atomic
        ]
    return policy


def build_payment_client(settings: Settings, budget: DailyBudget):
    """x402Client restricted to our guardrails. Requires a private key."""
    from eth_account import Account
    from x402 import AbortResult, x402Client
    from x402.mechanisms.evm.exact import register_exact_evm_client
    from x402.mechanisms.evm.signers import EthAccountSigner

    account = Account.from_key(settings.private_key)
    client = x402Client()
    register_exact_evm_client(client, EthAccountSigner(account), networks=settings.network,
                              policies=[_guard_policy(settings)])

    def before(ctx: Any):
        if budget.remaining() <= 0:
            return AbortResult(reason=f"daily limit of {budget.limit} paid checks reached")
        return None

    def after(ctx: Any):
        budget.record()

    client.on_before_payment_creation(before)
    client.on_after_payment_creation(after)
    return client, account.address


def valid_target(url: str) -> str | None:
    if not isinstance(url, str) or len(url) > 2048:
        return "url must be a string of at most 2048 characters"
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return "url is malformed"
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "url must be an http(s) URL with a host"
    return None


class ProvenPaidClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self.budget = DailyBudget(settings.daily_limit, settings.state_dir)
        self._transport = transport
        self.payer: str | None = None
        self._payment = None
        if settings.can_pay:
            self._payment, self.payer = build_payment_client(settings, self.budget)

    def _client(self, paying: bool) -> httpx.AsyncClient:
        inner = self._transport
        if paying:
            from x402.http.clients.httpx import x402AsyncTransport

            transport: httpx.AsyncBaseTransport = x402AsyncTransport(self._payment, inner)
        else:
            transport = inner or httpx.AsyncHTTPTransport()
        return httpx.AsyncClient(transport=transport, timeout=TIMEOUT_S, follow_redirects=False,
                                 headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                                 trust_env=True)

    async def methodology(self) -> str:
        async with self._client(paying=False) as c:
            r = await c.get(f"{self.settings.api_url}/methodology", headers={"Accept": "text/markdown"})
            r.raise_for_status()
            return r.text

    def status(self) -> dict:
        return {
            "api": self.settings.api_url,
            "network": self.settings.network,
            "paying_wallet": self.payer,
            "max_price_usd_per_check": str(self.settings.max_price_usd),
            "paid_checks_left_today": self.budget.remaining(),
            "ready_to_pay": self.settings.can_pay,
        }

    async def check(self, url: str) -> dict:
        problem = valid_target(url)
        if problem:
            return {"charged": False, "error": "invalid_input", "detail": problem}
        if not self.settings.can_pay:
            return {"charged": False, "error": "wallet_not_configured",
                    "detail": "Set PROVENPAID_WALLET_PRIVATE_KEY to a dedicated, low-balance wallet "
                              "holding USDC on Base. See the README."}
        from x402 import NoMatchingRequirementsError, PaymentAbortedError
        from x402.http.clients.httpx import PaymentError

        try:
            async with self._client(paying=True) as c:
                r = await c.get(f"{self.settings.api_url}/v1/check", params={"url": url.strip()})
        except PaymentAbortedError as e:
            return {"charged": False, "error": "budget", "detail": str(e)}
        except NoMatchingRequirementsError:
            return {"charged": False, "error": "price_or_network_refused",
                    "detail": f"ProvenPaid asked for more than ${self.settings.max_price_usd} or a payment "
                              f"other than USDC on {self.settings.network}; nothing was paid."}
        except PaymentError as e:
            cause = e.__cause__ or e
            if isinstance(cause, PaymentAbortedError):
                return {"charged": False, "error": "budget", "detail": str(cause)}
            if isinstance(cause, NoMatchingRequirementsError):
                return {"charged": False, "error": "price_or_network_refused",
                        "detail": f"ProvenPaid asked for more than ${self.settings.max_price_usd} or a payment "
                                  f"other than USDC on {self.settings.network}; nothing was paid."}
            return {"charged": False, "error": "payment_failed", "detail": type(cause).__name__}
        except httpx.HTTPError as e:
            return {"charged": False, "error": "network", "detail": type(e).__name__}

        try:
            body = r.json()
        except ValueError:
            body = {"detail": r.text[:500]}
        if r.status_code == 200:
            return {"charged": True, "report": body}
        if r.status_code == 402:
            return {"charged": False, "error": "payment_rejected",
                    "detail": "The payment was not accepted (for example insufficient USDC). Nothing was charged."}
        return {"charged": False, "status": r.status_code, **(body if isinstance(body, dict) else {"detail": body})}
