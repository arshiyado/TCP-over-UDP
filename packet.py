import struct

class Packet:
    HEADER_FORMAT = '!HHII B H H'
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

    def __init__(self, src_port=0, dest_port=0, seq_num=0, ack_num=0, syn=False, ack=False, fin=False,
                 payload=b'', window_size=4096):
        self.src_port = src_port
        self.dest_port = dest_port
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
            self.src_port,
            self.dest_port,
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

        src_port, dest_port, seq_num, ack_num, flags, payload_len, window_size = struct.unpack(
            cls.HEADER_FORMAT, header
        )

        syn = bool(flags & 0b100)
        ack = bool(flags & 0b010)
        fin = bool(flags & 0b001)

        return cls(
            src_port=src_port,
            dest_port=dest_port,
            seq_num=seq_num,
            ack_num=ack_num,
            syn=syn,
            ack=ack,
            fin=fin,
            payload=payload[:payload_len],
            window_size=window_size
        )