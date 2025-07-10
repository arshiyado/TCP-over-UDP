import random
import socket
import time
import queue
import threading
from packet import Packet

class TCPConnection:
    
    def __init__(self, udp_socket, peer_address, buffer_size=4096):
            self.socket = udp_socket
            self.peer = peer_address  # Tuple: (IP, port)

            # Extract ports
            self.local_port = self.socket.getsockname()[1]
            self.remote_port = self.peer[1]

            self.send_base = random.randint(0, 10000)
            self.next_seq_num = self.send_base
            self.ack_num = 0

            self.send_buffer = {}
            self.receive_buffer = {}
            self.expected_seq_num = 0

            self.receiver_window = buffer_size
            self.sender_window = buffer_size

            self.timeout = 1.0
            self.max_segment_size = 1000

            self.closed = False
            self.fin_received = False

            # Congestion control parameters
            self.cwnd = 1
            self.ssthresh = 16
            self.dup_ack_count = 0
            self.last_ack = None

            self.accept_queue = queue.Queue()
            self.accept_lock = threading.Lock()

    
    def handle_handshake_client(self):
        syn_packet = Packet(src_port=self.local_port, dest_port=self.remote_port, seq_num=self.send_base, syn=True, window_size=self.sender_window)
        self.socket.sendto(syn_packet.to_bytes(), self.peer)
        print(f"[CLIENT] Sent SYN {syn_packet}")

        while True:
            try:
                data, sender = self.socket.recvfrom(4096)
                if sender != self.peer:
                    continue
                packet = Packet.from_bytes(data)
                print(f"[CLIENT] Received {packet}")
                if packet.syn and packet.ack:
                    self.ack_num = packet.seq_num + 1
                    self.receiver_window = packet.window_size
                    self.expected_seq_num = packet.seq_num + 1
                    break
            except socket.timeout:
                print("[CLIENT] SYN-ACK timeout. Retrying...")
                self.socket.sendto(syn_packet.to_bytes(), self.peer)

        # ✅ Final ACK with ACK flag set to True
        ack_packet = Packet(src_port=self.local_port, dest_port=self.remote_port, seq_num=self.send_base + 1, ack_num=self.ack_num, ack=True,
                            window_size=self.sender_window)
        self.socket.sendto(ack_packet.to_bytes(), self.peer)
        print(f"[CLIENT] Sent final ACK {ack_packet}")

        self.next_seq_num = self.send_base + 1

        # ⚠️ Brief delay to ensure ACK arrives before data starts
        time.sleep(0.1)

        print("[CLIENT] Handshake complete.")


    def handle_handshake_server(self, data):
        packet = Packet.from_bytes(data)
        print(f"[SERVER] Received {packet}")

        if not packet.syn:
            raise Exception("Handshake error: Expected SYN")

        self.ack_num = packet.seq_num + 1
        self.send_base = random.randint(0, 10000)
        self.next_seq_num = self.send_base
        self.receiver_window = packet.window_size
        self.expected_seq_num = packet.seq_num + 1

        syn_ack_packet = Packet(src_port=self.local_port, dest_port=self.remote_port, seq_num=self.send_base, ack_num=self.ack_num,
                                syn=True, ack=True, window_size=self.sender_window)
        self.socket.sendto(syn_ack_packet.to_bytes(), self.peer)
        print(f"[SERVER] Sent SYN-ACK {syn_ack_packet}")

        while True:
            try:
                data, sender = self.socket.recvfrom(4096)
                if sender != self.peer:
                    continue
                packet = Packet.from_bytes(data)
                print(f"[SERVER] Received {packet}")
                if packet.ack and packet.ack_num == self.send_base + 1:
                    self.next_seq_num = self.send_base + 1
                    print("[SERVER] Handshake complete.")
                    break
            except socket.timeout:
                print("[SERVER] ACK timeout. Resending SYN-ACK...")
                self.socket.sendto(syn_ack_packet.to_bytes(), self.peer)

    def send(self, data):
        index = 0

        while index < len(data) or self.send_buffer:
            while index < len(data) and (self.next_seq_num - self.send_base) < min(self.receiver_window, self.cwnd * self.max_segment_size):
                segment = data[index: index + self.max_segment_size]
                packet = Packet(src_port=self.local_port, dest_port=self.remote_port, seq_num=self.next_seq_num, ack_num=self.ack_num,
                                payload=segment, window_size=self.sender_window)
                self.socket.sendto(packet.to_bytes(), self.peer)
                self.send_buffer[self.next_seq_num] = (packet, time.time())

                print(f"[SEND] Message: {segment}")
                print(f"       SEQ={packet.seq_num}, ACK={packet.ack_num}, win={packet.window_size}, "
                      f"SYN={packet.syn}, ACK_FLAG={packet.ack}, FIN={packet.fin}")

                self.next_seq_num += len(segment)
                index += len(segment)

            try:
                self.socket.settimeout(0.5)
                recv_data, sender = self.socket.recvfrom(4096)
                if sender != self.peer:
                    continue
                ack_packet = Packet.from_bytes(recv_data)

                if ack_packet.ack:
                    ack_num = ack_packet.ack_num
                    keys_to_remove = [seq for seq in self.send_buffer if seq < ack_num]
                    for seq in keys_to_remove:
                        del self.send_buffer[seq]

                    if ack_num == self.last_ack:
                        self.dup_ack_count += 1
                    else:
                        self.dup_ack_count = 1
                        self.last_ack = ack_num

                    if self.dup_ack_count == 3:
                        if ack_num in self.send_buffer:
                            self.socket.sendto(self.send_buffer[ack_num][0].to_bytes(), self.peer)
                        self.ssthresh = max(self.cwnd // 2, 1)
                        self.cwnd = 1

                    if ack_num > self.send_base:
                        if self.cwnd < self.ssthresh:
                            self.cwnd += 1  # slow start
                        else:
                            self.cwnd += 1 / self.cwnd  # congestion avoidance

                    self.send_base = ack_num
                    self.receiver_window = ack_packet.window_size
            except socket.timeout:
                pass

            current_time = time.time()
            for seq, (packet, timestamp) in list(self.send_buffer.items()):
                if current_time - timestamp > self.timeout:
                    self.socket.sendto(packet.to_bytes(), self.peer)
                    self.send_buffer[seq] = (packet, current_time)
                    print(f"[RETRANSMIT] Retransmitting packet starting at seq {seq}")
                    print(f"              SEQ={packet.seq_num}, ACK={packet.ack_num}, win={packet.window_size}, "
                          f"SYN={packet.syn}, ACK_FLAG={packet.ack}, FIN={packet.fin}")

    def recv(self):
        data_collected = b''

        while not self.closed:
            try:
                self.socket.settimeout(0.5)
                recv_data, sender = self.socket.recvfrom(4096)
                if sender != self.peer:
                    continue
                packet = Packet.from_bytes(recv_data)

                if packet.fin:
                    self._handle_fin(packet)
                    return b''

                if packet.payload:
                    seq = packet.seq_num

                    if seq == self.expected_seq_num:
                        data_collected += packet.payload
                        self.expected_seq_num += len(packet.payload)
                        self.ack_num = self.expected_seq_num

                        while self.expected_seq_num in self.receive_buffer:
                            data_collected += self.receive_buffer.pop(self.expected_seq_num)
                            self.expected_seq_num += len(packet.payload)
                            self.ack_num = self.expected_seq_num

                    elif seq > self.expected_seq_num:
                        self.receive_buffer[seq] = packet.payload

                    ack_packet = Packet(src_port=self.local_port, dest_port=self.remote_port, seq_num=self.next_seq_num,
                                        ack_num=self.expected_seq_num,
                                        ack=True,
                                        window_size=self.sender_window)
                    self.socket.sendto(ack_packet.to_bytes(), self.peer)

                    if data_collected:
                        return data_collected
            except socket.timeout:
                continue

    def close(self):
        fin_packet = Packet(src_port=self.local_port, dest_port=self.remote_port, seq_num=self.next_seq_num, ack_num=self.ack_num, fin=True,
                            window_size=self.sender_window)
        self.socket.sendto(fin_packet.to_bytes(), self.peer)
        print(f"[CLOSE] Sent FIN")

        start = time.time()
        while time.time() - start < 5:
            try:
                self.socket.settimeout(1.0)
                data, sender = self.socket.recvfrom(4096)
                if sender != self.peer:
                    continue
                packet = Packet.from_bytes(data)
                if packet.ack and packet.ack_num == self.next_seq_num + 1:
                    print(f"[CLOSE] Received ACK for our FIN")
                    break
            except socket.timeout:
                print("[CLOSE] Timeout. Resending FIN...")
                self.socket.sendto(fin_packet.to_bytes(), self.peer)

        self.next_seq_num += 1

        print("[CLOSE] Waiting for FIN from peer...")
        start = time.time()
        while time.time() - start < 5:
            if self.fin_received:
                print("[CLOSE] FIN already received in another thread.")
                break
            try:
                self.socket.settimeout(1.0)
                data, sender = self.socket.recvfrom(4096)
                if sender != self.peer:
                    continue
                packet = Packet.from_bytes(data)
                if packet.fin:
                    self._handle_fin(packet)
                    break
            except socket.timeout:
                print("[CLOSE] Timeout waiting for FIN. Closing anyway.")
                break

        self.closed = True
        print("[CLOSE] Connection fully closed.")

    def _handle_fin(self, packet):
        self.fin_received = True

        ack_packet = Packet(src_port=self.local_port, dest_port=self.remote_port, seq_num=self.next_seq_num,
                            ack_num=packet.seq_num + 1,
                            ack=True, window_size=self.sender_window)
        self.socket.sendto(ack_packet.to_bytes(), self.peer)
        print(f"[FIN] Received FIN. Sent ACK")

        time.sleep(0.1)
        fin_packet = Packet(src_port=self.local_port, dest_port=self.remote_port, seq_num=self.next_seq_num,
                            ack_num=packet.seq_num + 1,
                            fin=True, window_size=self.sender_window)
        self.socket.sendto(fin_packet.to_bytes(), self.peer)
        print(f"[FIN] Sent FIN in response")

        self.closed = True

def accept(self):
    # Blocks until a connection is available in the accept queue
    return self.accept_queue.get()

def enqueue_connection(self, connection):
    # Called when a connection has completed handshake
    self.accept_queue.put(connection)