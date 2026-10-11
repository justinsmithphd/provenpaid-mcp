# provenpaid-mcp

Give your agent a pre-payment check for paid x402 endpoints. **Evidence before you pay.**

<!-- mcp-name: com.provenpaid/mcp -->

[ProvenPaid](https://api.provenpaid.com) checks an x402 endpoint before your agent relies on it: is its payment challenge valid, and do real wallets actually pay it on-chain, come back, and how concentrated are payments? This MCP server exposes that check as a tool. **The first 10 checks are free, with no wallet and no setup.** After that it pays automatically, about **$0.01 in USDC on Base** per check, from a wallet you control.

Use it **once before relying on an unfamiliar endpoint**, not before every call.

## Tools

| Tool | Cost | What it does |
|---|---|---|
| `check_x402_endpoint(url)` | first 10 free, then about $0.01 | Validates the endpoint's x402 challenge and reports public on-chain evidence for its receiving address: distinct payers, repeat-payer share, payer concentration, coverage. |
| `provenpaid_methodology()` | free | How each signal is computed, what is not verified, and when a check is charged. |
| `provenpaid_status()` | free | Free checks left, paying wallet address, network, price cap and paid checks left today. |

You are **not charged** when the URL is invalid or unsafe, is not an x402 endpoint, or offers no payment option in USDC on Base. Results are evidence, not a verdict: ProvenPaid does not verify service quality or that an endpoint controls its receiving address.

## Install

Requires Python 3.11+. With [uv](https://docs.astral.sh/uv/):

```bash
uvx provenpaid-mcp
```

or `pip install provenpaid-mcp`.

### Try it free (no wallet)

```json
{
  "mcpServers": {
    "provenpaid": { "command": "uvx", "args": ["provenpaid-mcp"] }
  }
}
```

On first run it creates a local identity key (`~/.provenpaid-mcp/identity.key`, owner-only). The key holds no funds; it only lets ProvenPaid count your 10 free checks. Only checks that return evidence count.

### Keep going after the free checks

Add a dedicated, low-balance wallet:

```json
{
  "mcpServers": {
    "provenpaid": {
      "command": "uvx",
      "args": ["provenpaid-mcp"],
      "env": {
        "PROVENPAID_WALLET_PRIVATE_KEY": "0x...",
        "PROVENPAID_DAILY_LIMIT": "20"
      }
    }
  }
}
```

## Wallet safety

- Use a **dedicated wallet** holding only a few dollars of USDC on Base. Never use a wallet with meaningful funds.
- The key stays on your machine, in memory only. It is never logged, returned by a tool, or sent anywhere; only signed payment authorizations leave the process.
- No ETH is needed: the payment facilitator pays network fees.

Guardrails enforced **before anything is signed**:

| Setting | Default | Meaning |
|---|---|---|
| `PROVENPAID_MAX_PRICE_USD` | `0.01` | Refuse any check priced above this (hard ceiling `0.10`). |
| `PROVENPAID_DAILY_LIMIT` | `20` | Maximum paid checks per UTC day, persisted across restarts. |
| `PROVENPAID_NETWORK` | `eip155:8453` | Pay only on this network, only in its USDC. `eip155:84532` for Base Sepolia testing. |
| `PROVENPAID_API_URL` | `https://api.provenpaid.com` | Must be https. |
| `PROVENPAID_STATE_DIR` | `~/.provenpaid-mcp` | Where the daily counter is kept. |

## How it works

The server calls `GET https://api.provenpaid.com/v1/check?url=...`. The API answers HTTP 402 with x402 payment requirements; the official [x402 SDK](https://github.com/coinbase/x402) signs a single-use USDC authorization within the guardrails above and retries. Settlement happens only when the check delivers evidence. Methodology: https://api.provenpaid.com/methodology

## License

MIT
