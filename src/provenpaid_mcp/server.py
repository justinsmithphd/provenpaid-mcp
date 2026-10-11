"""MCP server (stdio). Run: provenpaid-mcp"""

from __future__ import annotations

import sys

from mcp.server import MCPServer

from . import __version__
from .client import ProvenPaidClient
from .config import ConfigError, load_settings

INSTRUCTIONS = (
    "ProvenPaid gives evidence about a paid x402 endpoint before you pay it: whether its payment "
    "challenge is valid and how many distinct wallets actually pay it on-chain, how many come back, "
    "and how concentrated payments are. Call check_x402_endpoint once before relying on an "
    "unfamiliar endpoint, not before every call. The first 10 checks per install are free with no "
    "wallet; after that each check costs about $0.01 in USDC on Base. Never charged when the target is invalid, "
    "not x402, or unsupported. Evidence, not a verdict."
)


def build_server(client: ProvenPaidClient) -> MCPServer:
    server = MCPServer("ProvenPaid", instructions=INSTRUCTIONS, version=__version__,
                       website_url="https://api.provenpaid.com")

    @server.tool()
    async def check_x402_endpoint(url: str) -> dict:
        """Check a paid x402 endpoint before paying it. First 10 checks free, then about $0.01 in USDC on Base.

        Returns payer depth first: how many distinct wallets paid the endpoint's receiving address
        (x402-style, last 30 days), repeat-payer share, payer concentration and coverage, with a
        one-line statement. Then the full on-chain detail and the payment challenge validation.
        Not charged for invalid, unsafe, non-x402 or unsupported URLs.
        """
        return await client.check(url)

    @server.tool()
    async def provenpaid_methodology() -> str:
        """Free. How ProvenPaid computes each signal, what it does not verify, and when it charges."""
        return await client.methodology()

    @server.tool()
    async def provenpaid_status() -> dict:
        """Free. The paying wallet address, network, per-check price cap and paid checks left today."""
        return client.status()

    return server


def main() -> None:
    try:
        settings = load_settings()
    except ConfigError as e:
        print(f"provenpaid-mcp: {e}", file=sys.stderr)
        sys.exit(2)
    build_server(ProvenPaidClient(settings)).run("stdio")


if __name__ == "__main__":
    main()
