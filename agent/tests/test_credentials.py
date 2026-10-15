"""Tests for docflow_agent.credentials."""

import os
import sys
import pytest

from docflow_agent.credentials import (
    CredentialStore,
    InMemoryCredentialStore,
    WindowsCredentialManagerStore,
    WindowsDpapiStore,
    get_credential_store,
)


class TestInMemoryCredentialStore:
    """Verify the in-memory test store honours the CredentialStore contract."""

    @pytest.fixture()
    def store(self) -> InMemoryCredentialStore:
        return InMemoryCredentialStore()

    def test_implements_interface(self, store: InMemoryCredentialStore) -> None:
        assert isinstance(store, CredentialStore)

    def test_store_and_get(self, store: InMemoryCredentialStore) -> None:
        store.store("device_refresh_token", "secret-value")
        assert store.get("device_refresh_token") == "secret-value"

    def test_get_missing_returns_none(self, store: InMemoryCredentialStore) -> None:
        assert store.get("nonexistent") is None

    def test_exists(self, store: InMemoryCredentialStore) -> None:
        assert store.exists("key") is False
        store.store("key", "val")
        assert store.exists("key") is True

    def test_delete_existing(self, store: InMemoryCredentialStore) -> None:
        store.store("key", "val")
        assert store.delete("key") is True
        assert store.get("key") is None

    def test_delete_missing(self, store: InMemoryCredentialStore) -> None:
        assert store.delete("nonexistent") is False

    def test_overwrite(self, store: InMemoryCredentialStore) -> None:
        store.store("key", "v1")
        store.store("key", "v2")
        assert store.get("key") == "v2"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
class TestWindowsCredentialManagerStore:
    """Verify Windows Credential Manager store implementation."""

    @pytest.fixture()
    def store(self) -> WindowsCredentialManagerStore:
        store = WindowsCredentialManagerStore(prefix="DocflowAgentTest_")
        yield store
        # Cleanup
        store.delete("test_token")
        store.delete("overwrite_token")

    def test_implements_interface(self, store: WindowsCredentialManagerStore) -> None:
        assert isinstance(store, CredentialStore)

    def test_roundtrip_store_and_get(self, store: WindowsCredentialManagerStore) -> None:
        key = "test_token"
        val = "secure-cred-val-987"
        store.store(key, val)
        assert store.exists(key) is True
        assert store.get(key) == val
        assert store.delete(key) is True
        assert store.exists(key) is False
        assert store.get(key) is None

    def test_overwrite(self, store: WindowsCredentialManagerStore) -> None:
        key = "overwrite_token"
        store.store(key, "first_value")
        assert store.get(key) == "first_value"
        store.store(key, "second_value")
        assert store.get(key) == "second_value"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
class TestWindowsDpapiStore:
    """Verify Windows DPAPI store implementation."""

    @pytest.fixture()
    def store(self, tmp_path) -> WindowsDpapiStore:
        return WindowsDpapiStore(directory=tmp_path / "credentials")

    def test_implements_interface(self, store: WindowsDpapiStore) -> None:
        assert isinstance(store, CredentialStore)

    def test_roundtrip_store_and_get(self, store: WindowsDpapiStore) -> None:
        key = "dpapi_token"
        val = "dpapi-secret-12345"
        store.store(key, val)
        assert store.exists(key) is True
        assert store.get(key) == val
        assert store.delete(key) is True
        assert store.exists(key) is False
        assert store.get(key) is None


class TestGetCredentialStoreFactory:
    """Verify get_credential_store factory selection."""

    def test_explicit_in_memory(self) -> None:
        store = get_credential_store(backend="in_memory")
        assert isinstance(store, InMemoryCredentialStore)

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DOCFLOW_AGENT_CREDENTIAL_STORE", "in_memory")
        store = get_credential_store()
        assert isinstance(store, InMemoryCredentialStore)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only test")
    def test_windows_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("DOCFLOW_AGENT_CREDENTIAL_STORE", raising=False)
        store = get_credential_store()
        assert isinstance(store, (WindowsCredentialManagerStore, WindowsDpapiStore))
