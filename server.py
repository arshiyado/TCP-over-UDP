"""Example echo server using pseudo‑TCP TCPSocket."""

from tcp_socket import TCPSocket


def main():
    sock = TCPSocket()
    sock.bind("0.0.0.0", 9000)
    sock.listen()
    print("[server] Listening on port 9000 …")
    conn = sock.accept()
    print("[server] Client connected:", conn.remote_addr)
    data = conn.receive(13)
    print("[server] Received:", data)
    conn.send(b"Hello back!")
    conn.close()


if __name__ == "__main__":
    main()
