import socket
import sys
import threading
import select
import time
from connection import TCPConnection
from packet import Packet

server_conn = None

active_connections = {}

def connection_handler(server_conn):
    while True:
        # Blocks until a connection is available in the queue
        conn = server_conn.accept()
        print(f"[INFO] Accepted new connection from {conn.peer}")
        threading.Thread(target=receive_loop, args=(conn,)).start()
        threading.Thread(target=send_loop, args=(conn,)).start()
lock = threading.Lock()

def receive_loop(conn):
    while True:
        data = conn.recv()
        if data == b'' or conn.closed:
            break
        print(f"\n[CLIENT {conn.peer}] {data.decode(errors='replace')}")

def send_loop(conn):
    prompt_shown = False
    while not conn.closed:
        try:
            if not prompt_shown:
                print(f"[SERVER to {conn.peer}] Type message: ", end="", flush=True)
                prompt_shown = True

            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
            if ready:
                msg = sys.stdin.readline().strip()
                prompt_shown = False  # reset for next input

                if msg.lower() == "exit":
                    conn.closed = True
                    time.sleep(0.2)
                    conn.close()
                    break

                broadcast(msg.encode())
        except Exception:
            break
def broadcast(message):
    with lock:
        for peer, c in list(active_connections.items()):
            try:
                if not c.closed:
                    c.send(message)
            except:
                continue

def client_thread(addr, first_packet_data, udp_socket):
    conn = TCPConnection(udp_socket, addr)
    conn.handle_handshake_server(first_packet_data)
    print(f"[SERVER] Connection established with {addr}")

    with lock:
        active_connections[addr] = conn

    recv_thread = threading.Thread(target=receive_loop, args=(conn,))
    send_thread = threading.Thread(target=send_loop, args=(conn,))
    recv_thread.start()
    send_thread.start()
    recv_thread.join()
    send_thread.join()

    conn.close()
    with lock:
        if addr in active_connections:
            del active_connections[addr]
    print(f"[SERVER] Connection to {addr} closed.")

def main():
    LOCAL_IP = "127.0.0.1"
    LOCAL_PORT = 12345
    BUFFER_SIZE = 4096

    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind((LOCAL_IP, LOCAL_PORT))
    udp_socket.settimeout(1.0)

    print(f"[SERVER] Listening on {LOCAL_IP}:{LOCAL_PORT}...")

    while True:
        try:
            data, addr = udp_socket.recvfrom(BUFFER_SIZE)
            packet = Packet.from_bytes(data)

            if addr not in active_connections:
                if packet.syn and not packet.ack:
                    print(f"[SERVER] Received SYN from {addr}")
                    threading.Thread(target=client_thread, args=(addr, data, udp_socket)).start()
                else:
                    print(f"[SERVER] Ignored non-SYN packet from {addr}")
            else:
                continue  # Handled in client thread
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("[SERVER] Shutting down.")
            break

if __name__ == "__main__":
    main()
