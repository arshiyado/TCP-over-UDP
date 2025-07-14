"""
Socket‑like API (listener + connector) built on UDP for pseudo‑TCP.
"""

from __future__ import annotations

import queue
import random
import socket
import threading
import time
from typing import Tuple

from packet import Packet, MAX_WINDOW, FLAG_SYN, FLAG_ACK
from connection import Connection
HANDSHAKE_TIMEOUT = 5.0  # seconds



class TCPSocket:
    """Provides bind()/listen()/accept() and connect() returning Connection objects."""

    def __init__(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(False)
        self._accept_q: queue.Queue[Connection] = queue.Queue()
        self._connections: dict[Tuple[str, int], Connection] = {}
        self._half_open: dict[Tuple[str, int], Tuple[int, float]] = {}  # remote -> local ISN
        self._running = True
        threading.Thread(target=self._listen_loop, daemon=True).start()

    # ---------------- server side ----------------
    def bind(self, host: str, port: int):
        self._sock.bind((host, port))
        self.local_addr = (host, port)

    def listen(self):
        # nothing extra – listener thread already active
        pass

    def accept(self, block: bool = True) -> Connection:
        if block:
            return self._accept_q.get()
        try:
            return self._accept_q.get_nowait()
        except queue.Empty:
            raise BlockingIOError

    # ---------------- client side ----------------
    def connect(self, host: str, port: int, timeout: float = 5.0) -> Connection:
        if self._sock.getsockname()[1] == 0:
            self._sock.bind(("0.0.0.0", 0))
        local_port = self._sock.getsockname()[1]
        remote = (host, port)
        isn = random.randint(0, 0xFFFFFFFF)
        syn = Packet(local_port, port, isn, 0, FLAG_SYN, MAX_WINDOW)
        start = time.time()
        rto = 0.5
        while True:
            self._sock.sendto(syn.to_bytes(), remote)
            deadline = time.time() + rto
            while time.time() < deadline:
                try:
                    data, addr = self._sock.recvfrom(65535)
                except BlockingIOError:
                    time.sleep(0.01)
                    continue
                if addr != remote:
                    continue
                try:
                    pkt = Packet.from_bytes(data)
                except ValueError:
                    continue
                if pkt.flag_set(FLAG_SYN) and pkt.flag_set(FLAG_ACK) and pkt.ack == (isn + 1) & 0xFFFFFFFF:
                    # send ACK and return Connection
                    ack_pkt = Packet(local_port, port, (isn + 1) & 0xFFFFFFFF, (pkt.seq + 1) & 0xFFFFFFFF,
                                     FLAG_ACK, MAX_WINDOW)
                    self._sock.sendto(ack_pkt.to_bytes(), remote)
                    conn = Connection(self._sock, self._sock.getsockname(), remote,
                                      (isn + 1) & 0xFFFFFFFF, pkt.seq, True)
                    self._connections[remote] = conn
                    return conn
            # timeout – exponential backoff within global timeout
            rto *= 2
            if time.time() - start > timeout:
                raise TimeoutError("connect timed out")

    # ---------------- internal listener ----------------
    def _listen_loop(self):
        while self._running:
            # --- cleanup stale half‑open handshakes ---
            now = time.time()
            for addr, (isn, ts) in list(self._half_open.items()):
                if now - ts > HANDSHAKE_TIMEOUT:
                    self._half_open.pop(addr, None)
            try:
                data, addr = self._sock.recvfrom(65535)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            try:
                pkt = Packet.from_bytes(data)
            except ValueError:
                continue
            # existing established connection
            if addr in self._connections:
                self._connections[addr]._handle(pkt)
                continue
            # handle SYN
            if pkt.flag_set(FLAG_SYN) and not pkt.flag_set(FLAG_ACK):
                isn_local = random.randint(0, 0xFFFFFFFF)
                syn_ack = Packet(self.local_addr[1], pkt.src_port, isn_local, (pkt.seq + 1) & 0xFFFFFFFF,
                                  FLAG_SYN | FLAG_ACK, MAX_WINDOW)
                self._sock.sendto(syn_ack.to_bytes(), addr)
                self._half_open[addr] = (isn_local, time.time())
                continue
            # handle ACK completing handshake
            if pkt.flag_set(FLAG_ACK) and addr in self._half_open:
                if pkt.ack == (self._half_open[addr][0] + 1) & 0xFFFFFFFF:
                    isn_local, _ = self._half_open.pop(addr)
                    conn = Connection(self._sock, self.local_addr, addr,
                                      (isn_local + 1) & 0xFFFFFFFF, pkt.seq - 1, False)
                    self._connections[addr] = conn
                    self._accept_q.put(conn)
                continue
            # ignore everything else
