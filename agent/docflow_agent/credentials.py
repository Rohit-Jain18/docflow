"""
Credential store interface and implementations for the Docflow Windows Agent.

Provides secure credential storage backed by:
- Windows Credential Manager (primary on Windows)
- Windows DPAPI (alternative OS-backed protection on Windows)
- In-memory store (test double and explicit non-Windows fallback)

SECURITY RULES (from docs/SECURITY.md §3):
- Refresh credentials use Windows Credential Manager or DPAPI.
- NEVER store secrets in plaintext .env, JSON, source code, logs,
  registry values, or bundled constants.
- Activation codes are transient and never persisted.
- WA_PLATFORM_DEVELOPER_TOKEN never belongs in Agent config.
"""

from __future__ import annotations

import hashlib
import logging
import os
import pathlib
import sys
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CredentialStore(ABC):
    """Abstract interface for secure credential storage.

    Implementations must store credentials using OS-level protection
    (Windows Credential Manager / DPAPI) — never plaintext files.
    """

    @abstractmethod
    def get(self, key: str) -> str | None:
        """Retrieve a stored credential by key.

        Returns:
            The credential value, or None if not found.
        """

    @abstractmethod
    def store(self, key: str, value: str) -> None:
        """Securely store a credential.

        Args:
            key:   Identifier for the credential (e.g. "device_refresh_token").
            value: The secret value to store.
        """

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove a stored credential.

        Returns:
            True if a credential was deleted, False if it did not exist.
        """

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check whether a credential exists without retrieving it.

        Returns:
            True if the credential exists in the store.
        """


# ---------------------------------------------------------------------------
# Windows Credential Manager backing (ctypes / advapi32)
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]


class WindowsCredentialManagerStore(CredentialStore):
    """Secure credential store backed by Windows Credential Manager.

    Uses advapi32.dll CredWriteW, CredReadW, and CredDeleteW via ctypes.
    Stores generic credentials under a namespaced target name.
    """

    DEFAULT_PREFIX = "DocflowAgent:"

    def __init__(self, prefix: str = DEFAULT_PREFIX) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsCredentialManagerStore requires Windows OS.")
        self._prefix = prefix

    def _target(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> str | None:
        import ctypes
        advapi32 = ctypes.windll.advapi32

        target = self._target(key)
        pcred = ctypes.POINTER(_CREDENTIAL)()
        # CRED_TYPE_GENERIC = 1
        res = advapi32.CredReadW(target, 1, 0, ctypes.byref(pcred))
        if not res:
            return None
        try:
            size = pcred.contents.CredentialBlobSize
            blob_ptr = pcred.contents.CredentialBlob
            data = ctypes.string_at(blob_ptr, size)
            return data.decode("utf-8")
        finally:
            advapi32.CredFree(pcred)

    def store(self, key: str, value: str) -> None:
        import ctypes
        advapi32 = ctypes.windll.advapi32

        target = self._target(key)
        raw_bytes = value.encode("utf-8")

        cred = _CREDENTIAL()
        cred.Type = 1  # CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.CredentialBlobSize = len(raw_bytes)
        cred.CredentialBlob = ctypes.cast(
            ctypes.create_string_buffer(raw_bytes),
            ctypes.POINTER(ctypes.c_byte),
        )
        cred.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "DocflowAgent"

        if not advapi32.CredWriteW(ctypes.byref(cred), 0):
            err = ctypes.GetLastError()
            raise RuntimeError(f"CredWriteW failed with error code {err}")

    def delete(self, key: str) -> bool:
        import ctypes
        advapi32 = ctypes.windll.advapi32

        target = self._target(key)
        res = advapi32.CredDeleteW(target, 1, 0)
        return bool(res)

    def exists(self, key: str) -> bool:
        return self.get(key) is not None


# ---------------------------------------------------------------------------
# Windows DPAPI backing (ctypes / crypt32)
# ---------------------------------------------------------------------------

class WindowsDpapiStore(CredentialStore):
    """Secure credential store backed by Windows DPAPI (CryptProtectData).

    Protects secrets using user-scoped DPAPI master key and persists
    ciphertext in a user-local directory.
    """

    def __init__(self, directory: pathlib.Path | None = None) -> None:
        if sys.platform != "win32":
            raise RuntimeError("WindowsDpapiStore requires Windows OS.")
        if directory is None:
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata:
                base = pathlib.Path(local_appdata) / "DocflowAgent"
            else:
                base = pathlib.Path.home() / ".docflow_agent"
            directory = base / "credentials"
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, key: str) -> pathlib.Path:
        safe_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self._dir / f"{safe_hash}.dpapi"

    def get(self, key: str) -> str | None:
        path = self._file_path(key)
        if not path.is_file():
            return None
        import ctypes
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        cipher = path.read_bytes()
        data_in = _DATA_BLOB(
            len(cipher),
            ctypes.cast(ctypes.create_string_buffer(cipher), ctypes.POINTER(ctypes.c_char)),
        )
        data_out = _DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x01
        if not crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, None, None, None, 1, ctypes.byref(data_out)
        ):
            return None
        try:
            raw = ctypes.string_at(data_out.pbData, data_out.cbData)
            return raw.decode("utf-8")
        finally:
            kernel32.LocalFree(data_out.pbData)

    def store(self, key: str, value: str) -> None:
        import ctypes
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32

        raw_bytes = value.encode("utf-8")
        data_in = _DATA_BLOB(
            len(raw_bytes),
            ctypes.cast(ctypes.create_string_buffer(raw_bytes), ctypes.POINTER(ctypes.c_char)),
        )
        data_out = _DATA_BLOB()
        # CRYPTPROTECT_UI_FORBIDDEN = 0x01
        if not crypt32.CryptProtectData(
            ctypes.byref(data_in), "DocflowAgent", None, None, None, 1, ctypes.byref(data_out)
        ):
            err = ctypes.GetLastError()
            raise RuntimeError(f"CryptProtectData failed with error code {err}")
        try:
            cipher = ctypes.string_at(data_out.pbData, data_out.cbData)
            path = self._file_path(key)
            path.write_bytes(cipher)
        finally:
            kernel32.LocalFree(data_out.pbData)

    def delete(self, key: str) -> bool:
        path = self._file_path(key)
        if path.is_file():
            path.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        return self._file_path(key).is_file()


# ---------------------------------------------------------------------------
# Development / testing stub
# ---------------------------------------------------------------------------

class InMemoryCredentialStore(CredentialStore):
    """In-memory credential store for testing only.

    WARNING: This stores secrets in process memory with NO OS-level
    protection. Never use in production.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def store(self, key: str, value: str) -> None:
        self._store[key] = value

    def delete(self, key: str) -> bool:
        try:
            del self._store[key]
            return True
        except KeyError:
            return False

    def exists(self, key: str) -> bool:
        return key in self._store


# ---------------------------------------------------------------------------
# Store Factory
# ---------------------------------------------------------------------------

def get_credential_store(backend: str | None = None) -> CredentialStore:
    """Get the appropriate credential store for the current environment.

    Resolution order:
    1. Explicit ``backend`` parameter ("credential_manager", "dpapi", or "in_memory")
    2. ``DOCFLOW_AGENT_CREDENTIAL_STORE`` environment variable
    3. Windows OS: WindowsCredentialManagerStore (falls back to WindowsDpapiStore)
    4. Non-Windows: InMemoryCredentialStore (with warning logged)
    """
    selected = (backend or os.environ.get("DOCFLOW_AGENT_CREDENTIAL_STORE", "")).strip().lower()

    if selected == "in_memory":
        return InMemoryCredentialStore()

    if selected == "dpapi":
        if sys.platform == "win32":
            return WindowsDpapiStore()
        logger.warning("DPAPI requested but not running on Windows; falling back to InMemoryCredentialStore")
        return InMemoryCredentialStore()

    if selected == "credential_manager":
        if sys.platform == "win32":
            return WindowsCredentialManagerStore()
        logger.warning("Credential Manager requested but not on Windows; falling back to InMemoryCredentialStore")
        return InMemoryCredentialStore()

    # Default platform resolution
    if sys.platform == "win32":
        try:
            return WindowsCredentialManagerStore()
        except Exception as exc:
            logger.warning(
                "Windows Credential Manager initialization failed (%s); trying DPAPI fallback",
                exc,
            )
            return WindowsDpapiStore()

    logger.warning("Non-Windows OS detected; using InMemoryCredentialStore test double")
    return InMemoryCredentialStore()
