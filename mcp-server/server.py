#!/usr/bin/env python3
"""Streamable-HTTP MCP server exposing the 6 coc-strategist tools (SPEC §5 Mode A)."""

from __future__ import annotations

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from coc_proxy import CoCProxy, ProxyError, json_dumps, json_loads

SERVER_INFO = {"name": "coc-strategist", "version": "2.0.0"}
PROTOCOL_VERSION = "2025-03-26"

# SPEC §5 Mode A: exact 6 MCP tools
TOOLS: list[dict[str, Any]] = [
    {
        "name": "coc_get_player",
        "description": "Fetch and normalize Clash of Clans player profile into compact tactical JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {"tag": {"type": "string", "description": "Player #TAG"}},
            "required": ["tag"],
        },
    },
    {
        "name": "coc_get_player_battlelog",
        "description": "Fetch the player's last 25 battles and army composition signatures.",
        "inputSchema": {
            "type": "object",
            "properties": {"tag": {"type": "string", "description": "Player #TAG"}},
            "required": ["tag"],
        },
    },
    {
        "name": "coc_get_clan_summary",
        "description": "Fetch clan stats and Town Hall distribution histogram.",
        "inputSchema": {
            "type": "object",
            "properties": {"tag": {"type": "string", "description": "Clan #TAG"}},
            "required": ["tag"],
        },
    },
    {
        "name": "coc_get_clan_members",
        "description": "Fetch sorted clan member roster with upgrade readiness scores.",
        "inputSchema": {
            "type": "object",
            "properties": {"tag": {"type": "string", "description": "Clan #TAG"}},
            "required": ["tag"],
        },
    },
    {
        "name": "coc_get_war_board",
        "description": "Fetch live war state: stars, remaining attacks, and opponent TH spread.",
        "inputSchema": {
            "type": "object",
            "properties": {"clan_tag": {"type": "string", "description": "Clan #TAG"}},
            "required": ["clan_tag"],
        },
    },
    {
        "name": "coc_get_cwl_group",
        "description": "Fetch CWL league group clans, round results, and mismatch risk.",
        "inputSchema": {
            "type": "object",
            "properties": {"clan_tag": {"type": "string", "description": "Clan #TAG"}},
            "required": ["clan_tag"],
        },
    },
]

_PROXY = CoCProxy()


def _dispatch_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "coc_get_player":
        return _PROXY.get_player(str(args.get("tag", "")))
    if name == "coc_get_player_battlelog":
        return _PROXY.get_player_battlelog(str(args.get("tag", "")))
    if name == "coc_get_clan_summary":
        return _PROXY.get_clan_summary(str(args.get("tag", "")))
    if name == "coc_get_clan_members":
        return _PROXY.get_clan_members(str(args.get("tag", "")))
    if name == "coc_get_war_board":
        return _PROXY.get_war_board(str(args.get("clan_tag", "")))
    if name == "coc_get_cwl_group":
        return _PROXY.get_cwl_group(str(args.get("clan_tag", "")))
    raise ValueError(f"Unknown tool: {name}")


class MCPHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Keep stdout clean and never log sensitive headers/tokens
        return

    def _requester_ip(self) -> str:
        xff = self.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
        return self.client_address[0]

    def _send_json(self, status: int, payload: Any) -> None:
        body = json_dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/health", "/mcp"):
            self._send_json(200, {"status": "ok", "server": SERVER_INFO})
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/mcp":
            self._send_json(404, {"error": "Not found"})
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        raw_body = self.rfile.read(length) if length > 0 else b""
        try:
            req = json_loads(raw_body)
        except Exception:
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            return

        if not isinstance(req, dict):
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}})
            return

        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        # JSON-RPC notification (no id)
        if req_id is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if method == "initialize":
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {"tools": {}},
                        "serverInfo": SERVER_INFO,
                    },
                },
            )
            return

        if method == "tools/list":
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"tools": TOOLS},
                },
            )
            return

        if method == "tools/call":
            tool_name = str(params.get("name", ""))
            tool_args = params.get("arguments") or {}
            try:
                _PROXY.check_ip_rate_limit(self._requester_ip())
                result_obj = _dispatch_tool(tool_name, tool_args)
                self._send_json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": json_dumps(result_obj)}],
                            "isError": False,
                        },
                    },
                )
            except (ProxyError, ValueError) as exc:
                self._send_json(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [{"type": "text", "text": str(exc)}],
                            "isError": True,
                        },
                    },
                )
            return

        self._send_json(
            200,
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            },
        )


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), MCPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
