import struct

# === Constants ===

MSS = 536  # bytes
DEFAULT_RTO = 0.5  # seconds, retransmit
MAX_WINDOW = 65535  # uint16
# assigned numbers for OR
FLAG_SYN = 0x01
FLAG_ACK = 0x02
FLAG_FIN = 0x04
FLAG_RST = 0x08

_HDR_FMT = "!HHIIBHH"  # src port, dst port, seq, ack, flags, window, length
_HDR_LEN = struct.calcsize(_HDR_FMT)


def _mod32_lt(a: int, b: int) -> bool:
    """Return True if sequence number *a* precedes *b* in modulo-2^32 space."""
    return ((a - b) & 0xFFFFFFFF) > 0x80000000


class Packet:

    __slots__ = (
        "src_port",
        "dst_port",
        "seq",
        "ack",
        "flags",
        "window",
        "payload",
    )

    def __init__(self, src_port: int, dst_port: int, seq: int = 0, ack: int = 0,
                 flags: int = 0, window: int = MAX_WINDOW, payload: bytes | bytearray = b""):
        self.src_port = src_port & 0xFFFF
        self.dst_port = dst_port & 0xFFFF
        self.seq = seq & 0xFFFFFFFF
        self.ack = ack & 0xFFFFFFFF
        self.flags = flags & 0xFF
        self.window = window & 0xFFFF
        self.payload = bytes(payload)

    # ------------------------------------------------------------------
    # (De)serialisation helpers
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        length = len(self.payload)
        header = struct.pack(
            _HDR_FMT,
            self.src_port,
            self.dst_port,
            self.seq,
            self.ack,
            self.flags,
            self.window,
            length,
        )
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "Packet":
        if len(data) < _HDR_LEN:
            raise ValueError("Packet too short")
        src, dst, seq, ack, flags, window, length = struct.unpack(_HDR_FMT, data[:_HDR_LEN])
        payload = data[_HDR_LEN:_HDR_LEN + length]
        return cls(src, dst, seq, ack, flags, window, payload)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def flag_set(self, f: int) -> bool:
        return bool(self.flags & f)

    def __repr__(self) -> str:  # pragma: no cover
        names = []
        for bit, name in ((FLAG_SYN, "SYN"), (FLAG_ACK, "ACK"), (FLAG_FIN, "FIN"), (FLAG_RST, "RST")):
            if self.flags & bit:
                names.append(name)
        return f"<Packet {','.join(names) or 'DATA'} seq={self.seq} ack={self.ack} len={len(self.payload)}>"