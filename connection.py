"""
Reliable byte‑stream Connection built on Packet and UDP socket.
Implements 3‑way handshake, data transfer with ACKs, 4‑way close, **retransmission**,
**basic TCP‑like congestion control (Tahoe/Reno)**.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Tuple

from packet import Packet, _mod32_lt, MSS, MAX_WINDOW, DEFAULT_RTO, FLAG_ACK, FLAG_FIN

log = logging.getLogger(__name__)


class Connection:
    """Represents one established pseudo‑TCP connection (duplex)."""

    # ------------------------------------------------------------------
    # Construction / state
    # ------------------------------------------------------------------

    def __init__(self, sock, local_addr: Tuple[str, int], remote_addr: Tuple[str, int],
                 snd_initial: int, rcv_initial: int, is_active: bool):
        self._sock = sock
        self._sock_lock = threading.Lock()

        self.local_addr = local_addr
        self.remote_addr = remote_addr

        # --- Sender sequence numbers ---
        self._snd_una = snd_initial  # oldest unacknowledged
        self._snd_nxt = snd_initial  # next sequence number
        self._snd_wnd = MAX_WINDOW   # receiver‑advertised window

        # --- Receiver state ---
        self._rcv_nxt = (rcv_initial + 1) & 0xFFFFFFFF
        self._rcv_wnd = MAX_WINDOW

        # --- Congestion‑control state ---
        self._cwnd = MSS            # congestion window (bytes)
        self._ssthresh = 65535      # initial slow‑start threshold
        self._dup_ack_cnt = 0
        self._last_ack = snd_initial

        # --- Buffers ---
        self._send_buf: deque[tuple[int, bytes]] = deque()
        self._recv_buf = bytearray()
        self._recv_cv = threading.Condition()

        # --- Timers & flags ---
        self._rto = DEFAULT_RTO
        self._timer: threading.Timer | None = None
        self._closing = False
        self._closed = threading.Event()

        # Launch RX handler thread
        threading.Thread(target=self._rx_loop, daemon=True).start()

        if is_active:
            self._start_timer()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, data: bytes):
        if self._closing:
            raise RuntimeError("Connection closing")
        offset = 0
        while offset < len(data):
            chunk = data[offset: offset + MSS]
            offset += len(chunk)
            with self._sock_lock:
                seq = self._snd_nxt
                self._snd_nxt = (self._snd_nxt + len(chunk)) & 0xFFFFFFFF
                self._send_buf.append((seq, chunk))
            self._pump_send()
        while self._send_buf:
            time.sleep(0.01)

    def receive(self, nbytes: int) -> bytes:
        output = bytearray()
        with self._recv_cv:
            while len(output) < nbytes:
                if self._recv_buf:
                    take = min(nbytes - len(output), len(self._recv_buf))
                    output += self._recv_buf[:take]
                    del self._recv_buf[:take]
                else:
                    self._recv_cv.wait()
        
        # --- Flow‑control: window update after application consumed data ---
        old_wnd = self._rcv_wnd
        self._rcv_wnd = max(0, MAX_WINDOW - len(self._recv_buf))
        if self._rcv_wnd > old_wnd and (self._rcv_wnd - old_wnd) >= MSS:
            # Notify peer about newly available window
            update = Packet(self.local_addr[1], self.remote_addr[1], self._snd_nxt, self._rcv_nxt,
                            FLAG_ACK, self._rcv_wnd)
            with self._sock_lock:
                self._send_raw(update)
        return bytes(output)

    def close(self):
        if self._closing:
            return
        self._closing = True
        with self._sock_lock:
            fin = Packet(self.local_addr[1], self.remote_addr[1], self._snd_nxt, self._rcv_nxt,
                          FLAG_FIN | FLAG_ACK, self._rcv_wnd)
            self._send_raw(fin)
            self._snd_nxt = (self._snd_nxt + 1) & 0xFFFFFFFF
        self._closed.wait()

    # ------------------------------------------------------------------
    # Congestion‑control helpers
    # ------------------------------------------------------------------

    def _in_slow_start(self) -> bool:
        return self._cwnd < self._ssthresh

    def _on_new_ack(self, acked_bytes: int):
        if self._in_slow_start():
            # Exponential growth
            self._cwnd += MSS
        else:
            # Congestion avoidance (linear)
            self._cwnd += MSS * MSS // self._cwnd
        self._dup_ack_cnt = 0
        log.debug("ACK advance → cwnd=%d ssthresh=%d", self._cwnd, self._ssthresh)

    def _on_dup_ack(self):
        self._dup_ack_cnt += 1
        if self._dup_ack_cnt == 3:
            # Fast retransmit / fast recovery (Tahoe/Reno mix)
            self._ssthresh = max(self._cwnd // 2, MSS)
            self._cwnd = self._ssthresh + 3 * MSS
            log.debug("Fast retransmit triggered, cwnd=%d ssthresh=%d", self._cwnd, self._ssthresh)
            # retransmit first unacked segment immediately
            if self._send_buf:
                seq, payload = self._send_buf[0]
                pkt = Packet(self.local_addr[1], self.remote_addr[1], seq, self._rcv_nxt,
                              FLAG_ACK, self._rcv_wnd, payload)
                self._send_raw(pkt)

    def _on_timeout_cc(self):
        self._ssthresh = max(self._cwnd // 2, MSS)
        self._cwnd = MSS
        self._dup_ack_cnt = 0
        log.debug("Timeout → cwnd=%d ssthresh=%d", self._cwnd, self._ssthresh)

    # ------------------------------------------------------------------
    # Internal timers
    # ------------------------------------------------------------------

    def _start_timer(self):
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self._rto, self._on_timeout)
        self._timer.daemon = True
        self._timer.start()

    def _on_timeout(self):
        with self._sock_lock:
            self._on_timeout_cc()
            if self._send_buf:
                seq, payload = self._send_buf[0]
                pkt = Packet(self.local_addr[1], self.remote_addr[1], seq, self._rcv_nxt,
                              FLAG_ACK, self._rcv_wnd, payload)
                self._send_raw(pkt)
                self._start_timer()

    # ------------------------------------------------------------------
    # Sending logic
    # ------------------------------------------------------------------

    def _pump_send(self):
        with self._sock_lock:
            while self._send_buf:
                outstanding = (self._snd_nxt - self._snd_una) & 0xFFFFFFFF
                wnd = min(self._cwnd, self._snd_wnd)
                if outstanding >= wnd:
                    break
                seq, payload = self._send_buf[0]
                pkt = Packet(self.local_addr[1], self.remote_addr[1], seq, self._rcv_nxt,
                              FLAG_ACK if payload else 0, self._rcv_wnd, payload)
                self._send_raw(pkt)
                if seq == self._snd_una:
                    self._start_timer()
                self._send_buf.popleft()

    def _send_raw(self, pkt: Packet):
        self._sock.sendto(pkt.to_bytes(), self.remote_addr)

    # ------------------------------------------------------------------
    # RX path
    # ------------------------------------------------------------------

    def _handle(self, pkt: Packet):
        # --- Flow‑control: update sender window with value advertised by peer ---
        self._snd_wnd = pkt.window or 1  # peer's remaining receive window (0 closes window)

        # ACK handling
        if pkt.flag_set(FLAG_ACK):
            if pkt.ack == self._last_ack:
                self._on_dup_ack()
            elif _mod32_lt(self._snd_una, pkt.ack):
                acked = (pkt.ack - self._snd_una) & 0xFFFFFFFF
                self._snd_una = pkt.ack
                self._on_new_ack(acked)
                self._last_ack = pkt.ack
                if self._snd_una == self._snd_nxt and self._timer:
                    self._timer.cancel()
                else:
                    self._start_timer()
            # else: old ACK, ignore

        # Data reception
        if pkt.payload:
            # --- Flow‑control: shrink our advertised window by newly buffered bytes ---
            self._rcv_wnd = max(0, MAX_WINDOW - len(self._recv_buf))
            if pkt.seq == self._rcv_nxt:
                self._recv_buf.extend(pkt.payload)
                self._rcv_nxt = (self._rcv_nxt + len(pkt.payload)) & 0xFFFFFFFF
                with self._recv_cv:
                    self._recv_cv.notify_all()
            ack = Packet(self.local_addr[1], self.remote_addr[1], self._snd_nxt, self._rcv_nxt,
                          FLAG_ACK, self._rcv_wnd)
            self._send_raw(ack)

        # FIN handling
        if pkt.flag_set(FLAG_FIN):
            self._rcv_nxt = (pkt.seq + 1) & 0xFFFFFFFF
            ack = Packet(self.local_addr[1], self.remote_addr[1], self._snd_nxt, self._rcv_nxt,
                          FLAG_ACK, self._rcv_wnd)
            self._send_raw(ack)
            if not self._closing:
                self.close()
            else:
                self._closed.set()

    def _rx_loop(self):
        while not self._closed.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            if addr != self.remote_addr:
                continue
            try:
                pkt = Packet.from_bytes(data)
            except ValueError:
                continue
            self._handle(pkt)
