from __future__ import annotations

import copy
import json
import sys
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from PySide6.QtCore import QCoreApplication

from vla_pet.errors import PetError
from vla_pet.mcp import MCPMessageCodec, MCPServerConfig, MCPStdioClient
from vla_pet.permissions import Capability, PermissionBroker
from vla_pet.persistence import StateRepository
from vla_pet.plugin_dispatcher import AsyncPluginDispatcher
from vla_pet.plugins import PluginHost, PluginManifest, PluginSandbox, default_plugin_directory
from vla_pet.signing import TrustStore, canonical_json, public_key_bytes, sign_payload


def test_two_bundled_plugins_validate_and_are_disabled_by_default(tmp_path: Path) -> None:
    root = default_plugin_directory().resolve()
    manifests = [
        PluginManifest.load(path, trusted_builtin_root=root)
        for path in sorted(root.iterdir())
        if path.is_dir()
    ]
    assert {item.name for item in manifests} == {"focus-helper", "companion-care"}
    with StateRepository(tmp_path / "pet.db") as repository:
        host = PluginHost(PermissionBroker(), repository)
        for manifest in manifests:
            host.add(manifest)
            assert not host.enabled(manifest.name)


def test_unsigned_third_party_plugin_is_refused(tmp_path: Path) -> None:
    source = default_plugin_directory() / "focus-helper"
    target = tmp_path / "third-party"
    target.mkdir()
    (target / "README.md").write_bytes((source / "README.md").read_bytes())
    raw = json.loads((source / "plugin.json").read_text())
    raw["metadata"]["builtin"] = False
    (target / "plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(PetError) as error:
        PluginManifest.load(target, trust_store=TrustStore())
    assert error.value.code == "plugin.signature.required"


def test_ed25519_signed_plugin_and_tamper_detection(tmp_path: Path) -> None:
    source = default_plugin_directory() / "focus-helper"
    target = tmp_path / "signed"
    target.mkdir()
    (target / "README.md").write_bytes((source / "README.md").read_bytes())
    raw = copy.deepcopy(json.loads((source / "plugin.json").read_text()))
    raw["metadata"]["builtin"] = False
    private = Ed25519PrivateKey.generate()
    trust = TrustStore({"test": public_key_bytes(private)})
    signature = sign_payload(private, "test", canonical_json(raw))
    raw["signature"] = {
        "algorithm": signature.algorithm,
        "key_id": signature.key_id,
        "value": signature.value,
    }
    (target / "plugin.json").write_text(json.dumps(raw), encoding="utf-8")
    manifest = PluginManifest.load(target, trust_store=trust)
    assert manifest.signature_key_id == "test"
    (target / "README.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(PetError) as error:
        PluginManifest.load(target, trust_store=trust)
    assert error.value.code == "plugin.integrity.invalid"


def test_plugin_host_requires_enable_and_all_capabilities(tmp_path: Path) -> None:
    root = default_plugin_directory().resolve()
    manifest = PluginManifest.load(root / "focus-helper", trusted_builtin_root=root)
    with StateRepository(tmp_path / "pet.db") as repository:
        broker = PermissionBroker()
        host = PluginHost(broker, repository)
        host.add(manifest)
        with pytest.raises(PetError):
            host.invoke(manifest.name, {})
        host.set_enabled(manifest.name, True)
        broker.grant(Capability.PLUGIN_EXECUTE, subject="plugin.focus-helper")
        broker.grant(Capability.TIMER_MANAGE, subject="plugin.focus-helper")
        result = host.invoke(manifest.name, {"hook": "timer.completed"})
        assert result["ok"] and "complete" in result["message"].lower()
        assert repository.get_plugin_value("plugin.focus-helper", "activity")["invocations"] == 1


def test_plugin_enablement_persists_and_dispatches_off_thread(tmp_path: Path) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    root = default_plugin_directory().resolve()
    manifest = PluginManifest.load(root / "focus-helper", trusted_builtin_root=root)
    database = tmp_path / "pet.db"
    broker = PermissionBroker()
    broker.grant(Capability.PLUGIN_EXECUTE, subject="plugin.focus-helper")
    broker.grant(Capability.TIMER_MANAGE, subject="plugin.focus-helper")
    with StateRepository(database) as repository:
        host = PluginHost(broker, repository)
        host.add(manifest)
        host.set_enabled(manifest.name, True)
        reloaded = PluginHost(broker, repository)
        reloaded.add(manifest)
        assert reloaded.enabled(manifest.name)
    dispatcher = AsyncPluginDispatcher(database, broker, (manifest,))
    results: list[object] = []
    dispatcher.finished.connect(lambda _hook, value: results.append(value))
    assert dispatcher.dispatch("focus.completed", {"minutes": 25})
    deadline = time.monotonic() + 3.0
    while not results and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    dispatcher.close()
    assert results and results[0][0]["ok"]
    with StateRepository(database) as repository:
        activity = repository.get_plugin_value("plugin.focus-helper", "activity")
        assert activity["last_hook"] == "focus.completed"


def test_sandbox_command_has_no_network_by_default() -> None:
    sandbox = PluginSandbox()
    if not sandbox.available:
        pytest.skip("bubblewrap unavailable")
    root = default_plugin_directory().resolve()
    raw = json.loads((root / "focus-helper" / "plugin.json").read_text())
    raw["spec"]["runtime"] = "python-subprocess"
    raw["spec"]["entrypoint"] = ["runner.py"]
    # Command construction is covered through a lightweight manifest copy.
    base = PluginManifest.load(root / "focus-helper", trusted_builtin_root=root)
    manifest = type(base)(
        **{**{field: getattr(base, field) for field in base.__dataclass_fields__}, "runtime": "python-subprocess", "entrypoint": ("README.md",)}
    )
    command = sandbox.command(manifest)
    assert "--unshare-all" in command and "--share-net" not in command


def test_mcp_codec_rejects_wrong_request_identity() -> None:
    encoded = MCPMessageCodec.encode(2, "tools/list")
    assert '"jsonrpc":"2.0"' in encoded
    assert MCPMessageCodec.decode('{"jsonrpc":"2.0","id":2,"result":{"tools":[]}}', 2) == {"tools": []}
    with pytest.raises(ValueError):
        MCPMessageCodec.decode('{"jsonrpc":"2.0","id":3,"result":{}}', 2)


def test_permission_gated_mcp_stdio_round_trip() -> None:
    server = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    method = request.get('method')
    if method == 'tools/list':
        result = {'tools': [{'name': 'wave', 'inputSchema': {'type': 'object'}}]}
    elif method == 'tools/call':
        result = {'content': [{'type': 'text', 'text': 'hello'}]}
    else:
        result = {'capabilities': {'tools': {}}}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
"""
    config = MCPServerConfig("test", (sys.executable, "-u", "-c", server), timeout_s=2.0)
    denied = MCPStdioClient(config, PermissionBroker())
    with pytest.raises(PetError):
        denied.start()
    broker = PermissionBroker()
    broker.grant(Capability.MCP_CONNECT, subject="mcp.test")
    client = MCPStdioClient(config, broker)
    try:
        client.start()
        assert client.list_tools()[0]["name"] == "wave"
        assert client.call_tool("wave", {})["content"][0]["text"] == "hello"
    finally:
        client.stop()
