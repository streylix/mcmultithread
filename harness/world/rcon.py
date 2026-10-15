"""Minimal Source RCON client (Minecraft server remote console)."""
import socket
import struct


class Rcon:
    def __init__(self, host, port, password, timeout=60.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.next_id = 1
        if self._request(3, password)[0] == -1:
            raise PermissionError("RCON authentication failed")

    def _send(self, kind, body):
        rid = self.next_id
        self.next_id += 1
        data = struct.pack("<ii", rid, kind) + body.encode() + b"\0\0"
        self.sock.sendall(struct.pack("<i", len(data)) + data)
        return rid

    def _recv(self):
        size = struct.unpack("<i", self._read(4))[0]
        data = self._read(size)
        rid, _ = struct.unpack("<ii", data[:8])
        return rid, data[8:-2].decode(errors="replace")

    def _read(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON connection closed")
            buf += chunk
        return buf

    def _request(self, kind, body):
        self._send(kind, body)
        return self._recv()

    def command(self, cmd):
        return self._request(2, cmd)[1]

    def close(self):
        self.sock.close()
