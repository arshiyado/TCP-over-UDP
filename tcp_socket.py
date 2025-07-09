from enum import Enum
import threading
import time
from packet import Packet

class SocketState(Enum):
    CLOSED = 0
    LISTEN = 1
    SYN_SENT = 2
    SYN_RECEIVED = 3
    ESTABLISHED = 4
    FIN_WAIT_1 = 5
    FIN_WAIT_2 = 6
    CLOSE_WAIT = 7
    LAST_ACK = 8
    TIME_WAIT = 9

class TCPSocket:
    def __init__(self, local_ip, local_port, remote_ip=None, remote_port=None, sock=None):
        self.local_ip = local_ip
        self.local_port = local_port
        self.remote_ip = remote_ip
        self.remote_port = remote_port
        self.state = SocketState.CLOSED
        self.seq_num = 1000
        self.ack_num = 0
        self.running = True
        self.send_lock = threading.Lock()
        self.recv_buffer = b""

        
        self.socket = sock

        self.receiver_thread = threading.Thread(target=self.receive_loop)
        self.receiver_thread.start()

    def send_packet(self, pkt):
        data = pkt.to_bytes()
        self.socket.sendto(data, (self.remote_ip, self.remote_port))

    def receive_loop(self):
        while self.running:
            try:
                data, addr = self.socket.recvfrom(4096)
                packet = Packet.from_bytes(data)
                self.handle_packet(packet)
            except Exception as e:
                continue

    def handle_packet(self, packet):
        if packet.flags.get("ACK") and self.state == SocketState.FIN_WAIT_1:
            print("[CLOSE] Received ACK for our FIN. Waiting for server FIN...")
            self.state = SocketState.FIN_WAIT_2

        elif packet.flags.get("FIN"):
            print("[RECV] FIN received.")
            ack_pkt = Packet(
                src_port=self.local_port,
                dst_port=self.remote_port,
                seq_num=self.seq_num,
                ack_num=packet.seq_num + 1,
                flags={"ACK": True}
            )
            self.send_packet(ack_pkt)

            if self.state == SocketState.ESTABLISHED:
                print("[CLOSE] Sending FIN to close.")
                fin_pkt = Packet(
                    src_port=self.local_port,
                    dst_port=self.remote_port,
                    seq_num=self.seq_num,
                    ack_num=packet.seq_num + 1,
                    flags={"FIN": True}
                )
                self.send_packet(fin_pkt)
                self.seq_num += 1
                self.state = SocketState.LAST_ACK

            elif self.state == SocketState.FIN_WAIT_2:
                print("[CLOSE] Connection closed (TIME_WAIT).")
                self.state = SocketState.TIME_WAIT
                self.running = False

        elif packet.flags.get("ACK") and self.state == SocketState.LAST_ACK:
            print("[CLOSE] Received ACK for our FIN. Closing now.")
            self.state = SocketState.CLOSED
            self.running = False

    def close(self):
        print("[CLOSE] Initiating FIN...")
        fin_pkt = Packet(
            src_port=self.local_port,
            dst_port=self.remote_port,
            seq_num=self.seq_num,
            ack_num=self.ack_num,
            flags={"FIN": True}
        )
        self.send_packet(fin_pkt)
        self.state = SocketState.FIN_WAIT_1
        self.seq_num += 1

        timeout = 3
        start_time = time.time()
        while self.running and (time.time() - start_time < 30):
            time.sleep(1)

        if self.state != SocketState.CLOSED:
            print("[CLOSE] Timeout. Force closing.")
            self.running = False
