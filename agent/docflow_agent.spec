# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for Docflow Windows Agent.

Builds a standalone console executable for Windows environments.
Ensures zero bundling of credentials, local PDFs, databases, or environment secrets.
"""

from pathlib import Path

block_cipher = None

# Base directory for the agent package
AGENT_DIR = Path.cwd()

hidden_imports = [
    "docflow_agent",
    "docflow_agent.activation",
    "docflow_agent.cli",
    "docflow_agent.client",
    "docflow_agent.config",
    "docflow_agent.credentials",
    "docflow_agent.health",
    "docflow_agent.logging",
    "docflow_agent.media",
    "docflow_agent.pdf",
    "docflow_agent.quarantine",
    "docflow_agent.queue",
    "docflow_agent.recipient",
    "docflow_agent.registration",
    "docflow_agent.retention",
    "docflow_agent.runtime",
    "docflow_agent.service",
    "docflow_agent.stability",
    "docflow_agent.sync",
    "docflow_agent.token_manager",
    "docflow_agent.watcher",
    "win32timezone",
    "win32service",
    "win32serviceutil",
    "win32event",
    "servicemanager",
]

a = Analysis(
    ["docflow_agent/__main__.py"],
    pathex=[str(AGENT_DIR)],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "pytest",
        "_pytest",
        "unittest",
        "test",
        "tests",
        "django",
        "rest_framework",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="docflow-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="docflow-agent",
)
