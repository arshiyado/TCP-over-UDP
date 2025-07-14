"""Example client for pseudo‑TCP demonstration."""

from tcp_socket import TCPSocket


def main():
    sock = TCPSocket()
    conn = sock.connect("127.0.0.1", 9000)
    conn.send(b"Hello, server!")
    reply = conn.receive(12)
    print("[client] Reply:", reply)
    conn.close()


if __name__ == "__main__":
    main()
