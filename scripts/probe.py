import json
import socket
import sys


def probe(command_type, params):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(12.0)
    s.connect(("localhost", 9877))
    s.sendall(json.dumps({"type": command_type, "params": params}).encode("utf-8"))
    buf = b""
    while True:
        chunk = s.recv(8192)
        if not chunk:
            break
        buf += chunk
        try:
            return json.loads(buf.decode("utf-8"))
        except ValueError:
            continue
    return json.loads(buf.decode("utf-8"))


if __name__ == "__main__":
    ct = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    print(json.dumps(probe(ct, params), indent=2))
