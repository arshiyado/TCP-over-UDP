import struct

class Packet:
    HEADER_FORMAT = '!II B H H'
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def __init__(self, seq_num=0, ack_num=0, syn=False, ack=False, fin=False,
                 payload=b'', window_size=4096):
        self.seq_num = seq_num
        self.ack_num = ack_num
        self.syn = syn
        self.ack = ack
        self.fin = fin
        self.payload = payload
        self.window_size = window_size

    def to_bytes(self):
        flags = (self.syn << 2) | (self.ack << 1) | self.fin
        header = struct.pack(
            self.HEADER_FORMAT,
            self.seq_num,
            self.ack_num,
            flags,
            len(self.payload),
            self.window_size
        )
        return header + self.payload

    @classmethod
    def from_bytes(cls, data):
        header = data[:cls.HEADER_SIZE]
        payload = data[cls.HEADER_SIZE:]

        seq_num, ack_num, flags, payload_len, window_size = struct.unpack(
            cls.HEADER_FORMAT, header)
        syn = bool((flags >> 2) & 1)
        ack = bool((flags >> 1) & 1)
        fin = bool(flags & 1)
        payload = payload[:payload_len]

        return cls(seq_num, ack_num, syn, ack, fin, payload, window_size)

    def __str__(self):
        return (f"Packet(seq={self.seq_num}, ack={self.ack_num}, SYN={self.syn}, "
                f"ACK={self.ack}, FIN={self.fin}, win={self.window_size}, payload={self.payload})")