"""Settings from environment variables. Fails closed on anything unsafe."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

MAINNET = "eip155:8453"
TESTNET = "eip155:84532"
USDC = {  # Circle USDC on Base, as listed in the x402 SDK's EVM constants (x402==2.8.0)
    MAINNET: "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    TESTNET: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
}
HARD_MAX_PRICE_USD = Decimal("0.10")  # no setting can authorize more than this per check
_KEY = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Settings:
    api_url: str = "https://api.provenpaid.com"
    network: str = MAINNET
    max_price_usd: Decimal = Decimal("0.01")
    daily_limit: int = 20
    state_dir: Path = Path.home() / ".provenpaid-mcp"
    private_key: str = field(default="", repr=False)

    @property
    def max_atomic(self) -> int:
        return int(self.max_price_usd * 1_000_000)  # USDC has 6 decimals

    @property
    def can_pay(self) -> bool:
        return bool(self.private_key)


def load_settings(env: dict[str, str] | None = None) -> Settings:
    env = dict(os.environ if env is None else env)

    api_url = env.get("PROVENPAID_API_URL", "https://api.provenpaid.com").strip().rstrip("/")
    parts = urlsplit(api_url)
    if parts.scheme != "https" or not parts.hostname or parts.path or parts.query:
        raise ConfigError("PROVENPAID_API_URL must be an https origin, e.g. https://api.provenpaid.com")

    network = env.get("PROVENPAID_NETWORK", MAINNET).strip()
    if network not in USDC:
        raise ConfigError(f"PROVENPAID_NETWORK must be {MAINNET} (Base) or {TESTNET} (Base Sepolia)")

    try:
        max_price = Decimal(env.get("PROVENPAID_MAX_PRICE_USD", "0.01").strip().lstrip("$"))
    except InvalidOperation as e:
        raise ConfigError("PROVENPAID_MAX_PRICE_USD must be a number like 0.01") from e
    if not Decimal("0") < max_price <= HARD_MAX_PRICE_USD:
        raise ConfigError(f"PROVENPAID_MAX_PRICE_USD must be above 0 and at most {HARD_MAX_PRICE_USD}")

    try:
        daily_limit = int(env.get("PROVENPAID_DAILY_LIMIT", "20"))
    except ValueError as e:
        raise ConfigError("PROVENPAID_DAILY_LIMIT must be a whole number") from e
    if not 0 < daily_limit <= 10_000:
        raise ConfigError("PROVENPAID_DAILY_LIMIT must be between 1 and 10000")

    key = env.get("PROVENPAID_WALLET_PRIVATE_KEY", "").strip()
    if key and not _KEY.match(key):
        raise ConfigError("PROVENPAID_WALLET_PRIVATE_KEY is not a 32-byte hex private key")

    state_dir = Path(env.get("PROVENPAID_STATE_DIR", str(Path.home() / ".provenpaid-mcp")))
    return Settings(api_url, network, max_price, daily_limit, state_dir, key)
