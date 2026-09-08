#!/usr/bin/env python3
"""Minimal Kea Control Agent mock for local LeaseLurker development."""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HOST = "0.0.0.0"
PORT = 8000
COMMANDS = ["config-get", "lease4-get-all", "list-commands", "status-get"]


def command_response(payload: object, now: int | None = None) -> list[dict[str, Any]]:
    """Return a Kea-compatible response envelope for a control command."""
    if not isinstance(payload, dict):
        return [{"result": 1, "text": "Request must be a JSON object."}]

    command = payload.get("command")
    if command == "list-commands":
        return [{"result": 0, "arguments": COMMANDS, "text": "4 commands found."}]
    if command == "status-get":
        return [
            {
                "result": 0,
                "arguments": {"pid": 1, "reload": 0, "uptime": 3600},
                "text": "Kea DHCPv4 server status returned.",
            }
        ]
    if command == "config-get":
        return [
            {
                "result": 0,
                "arguments": {
                    "Dhcp4": {
                        "shared-networks": [
                            {
                                "name": "Development",
                                "subnet4": [{"id": 1, "subnet": "192.0.2.0/24"}],
                            }
                        ],
                        "subnet4": [{"id": 2, "subnet": "198.51.100.0/24"}],
                    }
                },
                "text": "Configuration successful.",
            }
        ]
    if command == "lease4-get-all":
        timestamp = now if now is not None else int(time.time())
        requested = payload.get("arguments", {}).get("subnets", [])
        leases = [
            {
                "ip-address": "192.0.2.42",
                "hostname": "workstation-042.example.test.",
                "hw-address": "00:1b:63:84:45:e6",
                "subnet-id": 1,
                "cltt": timestamp - 300,
                "valid-lft": 3600,
                "state": 0,
            },
            {
                "ip-address": "192.0.2.77",
                "hostname": "notebook-alice.example.test.",
                "hw-address": "3c:22:fb:12:34:56",
                "subnet-id": 1,
                "cltt": timestamp - 60,
                "valid-lft": 7200,
                "state": 0,
            },
            {
                "ip-address": "198.51.100.9",
                "hostname": "hidden-device.example.test.",
                "hw-address": "00:11:22:33:44:55",
                "subnet-id": 2,
                "cltt": timestamp - 60,
                "valid-lft": 3600,
                "state": 0,
            },
        ]
        selected = [lease for lease in leases if lease["subnet-id"] in requested]
        return [
            {
                "result": 0 if selected else 3,
                "arguments": {"leases": selected},
                "text": f"{len(selected)} IPv4 lease(s) found.",
            }
        ]
    return [{"result": 1, "text": f"Unsupported command: {command}"}]


class KeaMockHandler(BaseHTTPRequestHandler):
    server_version = "LeaseLurkerKeaMock/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_json({"status": "ok"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._is_authorized():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("Content-Type", "application/json")
            self.send_header("WWW-Authenticate", 'Basic realm="Kea Control Agent"')
            self.end_headers()
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
        except ValueError, json.JSONDecodeError:
            self._send_json(
                [{"result": 1, "text": "Invalid JSON request."}],
                HTTPStatus.BAD_REQUEST,
            )
            return
        self._send_json(command_response(payload))

    def _is_authorized(self) -> bool:
        username = os.environ.get("MOCK_KEA_USERNAME")
        password = os.environ.get("MOCK_KEA_PASSWORD")
        if username is None and password is None:
            return True
        if username is None or password is None:
            return False
        expected = (
            "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        )
        authorization = self.headers.get("Authorization", "")
        return secrets.compare_digest(authorization, expected)

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"mock-kea: {format % args}", flush=True)


def main() -> None:
    print(f"Mock Kea Control Agent listening on {HOST}:{PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), KeaMockHandler).serve_forever()


if __name__ == "__main__":
    main()
