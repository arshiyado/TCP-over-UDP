"""
Multi-client chat over pseudo-TCP with custom letter-shift cipher.

Usage:
  python chat.py server
  python chat.py client <server>
Typing “quit” on either side cleanly closes the connection.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import List, Callable

from tcp_socket import TCPSocket
from packet import Packet

PORT = 9000  # server port

# ---------------------------------------------------------------------------  cipher helpers
_SHIFTS = [10, 2, 16, 23, 25]  # per-character shift pattern


def _shift_char(ch: str, k: int) -> str:
    if 'a' <= ch <= 'z':
        base = ord('a')
        return chr((ord(ch) - base + k) % 26 + base)
    if 'A' <= ch <= 'Z':
        base = ord('A')
        return chr((ord(ch) - base + k) % 26 + base)
    return ch


def encrypt(text: str) -> bytes:
    return ''.join(_shift_char(ch, _SHIFTS[i % 5]) for i, ch in enumerate(text)).encode()


def decrypt(data: bytes) -> str:
    txt = data.decode(errors='ignore')
    return ''.join(_shift_char(ch, (26 - _SHIFTS[i % 5]) % 26) for i, ch in enumerate(txt))

# ---------------------------------------------------------------------------  packet logging (optional, unchanged)
_original_to_bytes = Packet.to_bytes
def _to_bytes_logged(self: Packet):
    blob = _original_to_bytes(self)
    logging.debug("TX %s", self)
    return blob
Packet.to_bytes = _to_bytes_logged  # type: ignore

_original_from_bytes = Packet.from_bytes
def _from_bytes_logged(data: bytes) -> Packet:
    pkt = _original_from_bytes(data)
    logging.debug("RX %s", pkt)
    return pkt
Packet.from_bytes = staticmethod(_from_bytes_logged)  # type: ignore

# ---------------------------------------------------------------------------  I/O helpers
def _reader(conn, tag: str):
    """Read bytes until newline; decrypt & display."""
    buf = bytearray()
    while True:
        try:
            ch = conn.receive(1)
        except Exception as exc:
            logging.error("%s receive error: %s", tag, exc)
            break

        if not ch:
            continue

        if ch == b"\n":
            if buf:
                msg = decrypt(bytes(buf))
                print(f"[peer:{tag}] {msg}")
                logging.info("[peer:%s] %s", tag, msg)
                if msg.strip() == "quit":
                    try:
                        conn.close()        # ✨ NEW — clean shutdown
                    finally:
                        break
                buf.clear()
        else:
            buf.extend(ch)


def _writer(get_conns: Callable[[], List]):
    """Encrypt each input line and broadcast to all live connections."""
    for line in sys.stdin:
        line_txt = line.rstrip("\n")
        cipher = encrypt(line_txt) + b"\n"

        # send to every connection
        for c in list(get_conns()):
            try:
                c.send(cipher)
            except Exception as exc:
                logging.error("send to %s failed: %s", c.remote_addr, exc)

        print(f"[me] {line_txt}")
        logging.info("[me] %s", line_txt)

        if line_txt.strip() == "quit":
            # ✨ NEW — close all connections before exit
            for c in list(get_conns()):
                try:
                    c.close()
                except Exception:
                    pass
            break

# ---------------------------------------------------------------------------  server / client
def run_server():
    sock = TCPSocket()
    sock.bind("0.0.0.0", PORT)
    sock.listen()
    print(f"[server] Listening on port {PORT}…")

    connections: List = []
    conns_lock = threading.Lock()

    def accept_loop():
        while True:
            conn = sock.accept()
            with conns_lock:
                connections.append(conn)
            tag = f"{conn.remote_addr[0]}:{conn.remote_addr[1]}"
            print(f"[server] New client {tag}")
            threading.Thread(target=_reader, args=(conn, tag), daemon=True).start()

    threading.Thread(target=accept_loop, daemon=True).start()
    _writer(lambda: connections)


def run_client(host: str):
    sock = TCPSocket()
    conn = sock.connect(host, PORT)
    print("[client] Connected to", host)
    threading.Thread(target=_reader, args=(conn, "server"), daemon=True).start()
    _writer(lambda: [conn])

# ---------------------------------------------------------------------------  entry-point
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    if len(sys.argv) == 2 and sys.argv[1] == "server":
        run_server()
    elif len(sys.argv) == 3 and sys.argv[1] == "client":
        run_client(sys.argv[2])
    else:
        print("Usage:\n  python chat.py server\n  python chat.py client <server>")
