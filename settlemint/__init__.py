"""Settlemint: a self-settling event market for NEAR.

This package is the off-chain half of milestone 1. `model.py` is a pure-Python
reimplementation of the NEAR contract's settlement arithmetic, kept byte-for-byte
in agreement with the Rust `payout_of` / `settle` logic by the parity tests in
`tests/`. `near.py` is the adapter seam: it talks to a real NEAR testnet over
JSON-RPC when credentials are present, and otherwise replays a deterministic
offline fixture so the whole thing runs keyless.
"""

from .model import EventMarket, Outcome, Phase

__all__ = ["EventMarket", "Outcome", "Phase"]
__version__ = "0.1.0"
