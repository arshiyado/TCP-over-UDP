import socket
import threading
from connection import TCPConnection
import time
def receive_loop(conn):
    while True:
        data = conn.recv()
        if data == b'':
            break
        if data:
            print(f"\n[SERVER] {data.decode(errors='replace')}")


def send_loop(conn):
    while True:
        try:
            msg = input("[CLIENT] Type message: ")
            if msg.lower() == "exit":
                conn.closed = True  # Signal to recv thread to stop reading
                time.sleep(0.2) 
                conn.close()
                break
            conn.send(msg.encode())
        except Exception:
            break

def main():
    SERVER_IP = "127.0.0.1"
    SERVER_PORT = 12345
    LOCAL_PORT = 54321
    BUFFER_SIZE = 4096

    # udp_socket.bind(("", LOCAL_PORT))
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.bind(("", 0))  # OS picks an available port
    udp_socket.settimeout(1.0)

    conn = TCPConnection(udp_socket, (SERVER_IP, SERVER_PORT))
    conn.handle_handshake_client()

    print(f"[CLIENT] Connected to server at {SERVER_IP}:{SERVER_PORT}")

    time.sleep(0.1)  # Allow server to process ACK

    
    recv_thread = threading.Thread(target=receive_loop, args=(conn,))
    send_thread = threading.Thread(target=send_loop, args=(conn,))
    recv_thread.start()
    send_thread.start()

    recv_thread.join()
    send_thread.join()

    print("[CLIENT] Connection closed.")

if __name__ == "__main__":
    main()
