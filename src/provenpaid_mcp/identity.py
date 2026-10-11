"""A local key that identifies this install for ProvenPaid's free tier. It holds no funds.

Created on first use at <state dir>/identity.key with owner-only permissions. It signs free-check
requests (EIP-191) so the server can count 10 free checks per install. It is never used to pay;
paying uses PROVENPAID_WALLET_PRIVATE_KEY, a separate wallet you fund yourself.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_defunct


def message_for(url: str, timestamp: int) -> str:
    # Must match the server exactly (x402check.free.message_for).
    return f"ProvenPaid free check\nurl: {url}\ntimestamp: {timestamp}"


def load_or_create(state_dir: Path):
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "identity.key"
    if path.exists():
        return Account.from_key(path.read_text().strip())
    acct = Account.create()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(acct.key.hex())
    return acct


def free_headers(acct, url: str, now: float | None = None) -> dict[str, str]:
    ts = int(now if now is not None else time.time())
    sig = Account.sign_message(encode_defunct(text=message_for(url, ts)), acct.key).signature.hex()
    return {"X-ProvenPaid-Address": acct.address, "X-ProvenPaid-Timestamp": str(ts),
            "X-ProvenPaid-Signature": sig if sig.startswith("0x") else "0x" + sig}
