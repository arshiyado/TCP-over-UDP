"""
Multi‑client chat over pseudo‑TCP with custom letter‑shift cipher and verbose logging.

Usage:
  python chat.py server            # listen on port 9000 (multi‑client)
  python chat.py client <server>   # connect to host:9000

Typing «quit» در هر سمت اتصال را می‌بندد.
رمزنگاری: برای کاراکترهای الفبایی بر اساس اندیس (mod 5) شیفت سزاری متفاوت اعمال می‌شود:
  idx%5==0 → +10، 1→+2، 2→+16، 3→+23، 4→+25. کاراکترهای غیرحرفی دست‌نخورده می‌مانند.
"""

from __future__ import annotations

import logging
import sys
import threading
from typing import List, Callable

from tcp_socket import TCPSocket
from packet import Packet

PORT = 9000  # ثابت پورت سرور

# ---------------------------------------------------------------------------
# Caesar‑family custom cipher helpers
# ---------------------------------------------------------------------------

_SHIFTS = [10, 2, 16, 23, 25]  # per index mod 5


def _shift_char(ch: str, k: int) -> str:
    if 'a' <= ch <= 'z':
        base = ord('a')
        return chr((ord(ch) - base + k) % 26 + base)
    if 'A' <= ch <= 'Z':
        base = ord('A')
        return chr((ord(ch) - base + k) % 26 + base)
    return ch  # non‑alpha unchanged


def encrypt(text: str) -> bytes:
    out = [
        _shift_char(ch, _SHIFTS[i % 5]) for i, ch in enumerate(text)
    ]
    return ''.join(out).encode()


def decrypt(data: bytes) -> str:
    txt = data.decode(errors='ignore')
    out = [
        _shift_char(ch, (26 - _SHIFTS[i % 5]) % 26) for i, ch in enumerate(txt)
    ]
    return ''.join(out)

# ---------------------------------------------------------------------------
# Runtime packet logging (unchanged)
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _reader(conn, tag: str):
    """Read bytes until plaintext newline, then decrypt & display."""
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
                    break
                buf.clear()
        else:
            buf.extend(ch)


def _writer(get_conns: Callable[[], List]):
    """Encrypt each line, keep plain newline, broadcast to all connections."""
    for line in sys.stdin:
        line_txt = line.rstrip("\n")
        cipher = encrypt(line_txt) + b"\n"  # newline delimiter remains plain
        for c in list(get_conns()):
            try:
                c.send(cipher)
            except Exception as exc:
                logging.error("send to %s failed: %s", c.remote_addr, exc)
        print(f"[me] {line_txt}")
        logging.info("[me] %s", line_txt)
        if line_txt.strip() == "quit":
            break

# ---------------------------------------------------------------------------
# Server / Client entry points
# ---------------------------------------------------------------------------

def run_server():
    sock = TCPSocket()
    sock.bind("0.0.0.0", PORT)
    sock.listen()
    print(f"[server] Listening on port {PORT} …")

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

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

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
