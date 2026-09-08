"""
Local static frontend server.
"""

import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
HOST = "127.0.0.1"
PORT = 5174


if __name__ == "__main__":
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(FRONTEND_DIR))
    server = ThreadingHTTPServer((HOST, PORT), handler)
    print(f"Serving frontend at http://{HOST}:{PORT}")
    server.serve_forever()
