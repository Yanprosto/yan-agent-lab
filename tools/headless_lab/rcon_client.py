"""Minimal Source RCON client for the headless lab server (password from server.properties)."""

from __future__ import annotations

import socket
import struct
import sys

HOST = "127.0.0.1"
PORT = 25575
PASSWORD = "yanlab-local"


def _packet(request_id: int, kind: int, body: str) -> bytes:
    data = struct.pack("<ii", request_id, kind) + body.encode() + b"\0\0"
    return struct.pack("<i", len(data)) + data


def _receive(sock: socket.socket) -> str:
    size = struct.unpack("<i", sock.recv(4))[0]
    data = b""
    while len(data) < size:
        data += sock.recv(size - len(data))
    return data[8:-2].decode(errors="replace")


def run(commands: list[str]) -> str:
    """Send commands in order and return the transcript."""
    lines = []
    with socket.create_connection((HOST, PORT), timeout=10) as sock:
        sock.sendall(_packet(1, 3, PASSWORD))
        _receive(sock)
        for command in commands:
            sock.sendall(_packet(2, 2, command))
            lines.append(f"> {command}\n{_receive(sock)}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(run(sys.argv[1:]))
