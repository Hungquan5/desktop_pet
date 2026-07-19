from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vla_pet.permissions import Capability, PermissionBroker


@dataclass(frozen=True, slots=True)
class MCPServerConfig:
    name: str
    command: tuple[str, ...]
    timeout_s: float = 20.0

    def validate(self) -> None:
        if not self.name.strip() or not self.command:
            raise ValueError("MCP server name and command are required")
        if not Path(self.command[0]).is_absolute() or not Path(self.command[0]).is_file():
            raise ValueError("MCP executable must be an existing absolute path")


class MCPMessageCodec:
    @staticmethod
    def encode(request_id: int, method: str, params: dict[str, Any] | None = None) -> str:
        return json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
            separators=(",", ":"),
        ) + "\n"

    @staticmethod
    def decode(line: str, request_id: int) -> dict[str, Any]:
        value = json.loads(line)
        if not isinstance(value, dict) or value.get("jsonrpc") != "2.0" or value.get("id") != request_id:
            raise ValueError("Invalid MCP JSON-RPC response")
        if "error" in value:
            raise RuntimeError(f"MCP error: {value['error']}")
        result = value.get("result", {})
        if not isinstance(result, dict):
            raise ValueError("MCP result must be an object")
        return result


class MCPStdioClient:
    """Permission-gated stdio bridge; disabled unless explicitly configured."""

    def __init__(self, config: MCPServerConfig, broker: PermissionBroker) -> None:
        config.validate()
        self.config = config
        self.broker = broker
        self._process: subprocess.Popen[str] | None = None
        self._next_id = 1

    def start(self) -> None:
        self.broker.require(Capability.MCP_CONNECT, subject=f"mcp.{self.config.name}")
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            list(self.config.command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
        )
        self.request(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "vla-pet", "version": "1.0.0"},
            },
        )

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("MCP server is not running")
        identifier = self._next_id
        self._next_id += 1
        self._process.stdin.write(MCPMessageCodec.encode(identifier, method, params))
        self._process.stdin.flush()
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vla-pet-mcp-read")
        future = pool.submit(self._process.stdout.readline, 64 * 1024)
        try:
            line = future.result(timeout=self.config.timeout_s)
        except TimeoutError as exc:
            self.stop()
            raise TimeoutError(f"MCP request exceeded {self.config.timeout_s:.1f}s") from exc
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        if not line:
            raise RuntimeError("MCP server closed without a response")
        return MCPMessageCodec.decode(line, identifier)

    def list_tools(self) -> tuple[dict[str, Any], ...]:
        result = self.request("tools/list")
        tools = result.get("tools", [])
        if not isinstance(tools, list):
            raise ValueError("MCP tools response is malformed")
        return tuple(item for item in tools if isinstance(item, dict))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.broker.require(Capability.MCP_CONNECT, subject=f"mcp.{self.config.name}")
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def stop(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)
