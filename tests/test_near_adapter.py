"""The NEAR adapter seam: keyless offline by default, testnet-only when live."""

import pytest

from settlemint.near import (
    LiveNearClient,
    OfflineNearClient,
    build_client,
)


def test_build_client_is_offline_without_creds(monkeypatch):
    monkeypatch.delenv("NEAR_RPC_URL", raising=False)
    monkeypatch.delenv("NEAR_SIGNER", raising=False)
    c = build_client()
    assert isinstance(c, OfflineNearClient)
    assert c.backend == "offline"


def test_build_client_goes_live_with_testnet_creds(monkeypatch):
    monkeypatch.setenv("NEAR_RPC_URL", "https://rpc.testnet.near.org")
    monkeypatch.setenv("NEAR_SIGNER", "operator.testnet")
    c = build_client()
    assert isinstance(c, LiveNearClient)
    assert c.backend == "live"


def test_live_client_refuses_mainnet():
    with pytest.raises(ValueError, match="testnet only"):
        LiveNearClient("https://rpc.mainnet.near.org", "operator.near")


def test_live_client_requires_testnet_host():
    with pytest.raises(ValueError, match="testnet"):
        LiveNearClient("https://example.com/rpc", "operator.testnet")


def test_live_client_makes_no_call_without_key():
    c = LiveNearClient("https://rpc.testnet.near.org", "operator.testnet")
    with pytest.raises(RuntimeError, match="milestone-3 seam"):
        c.settle(0, "alice.testnet")
