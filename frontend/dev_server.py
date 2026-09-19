"""Serve Navora with a same-origin proxy to its local FastAPI backend."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def __init__(self, *args, backend, **kwargs):
        self.backend = backend.rstrip("/")
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if not self.path.startswith("/api/"):
            return super().do_GET()
        try:
            response = urlopen(self.backend + self.path[4:], timeout=30)
        except HTTPError as error:
            response = error
        except URLError:
            self.send_error(502, "Navora backend is unavailable")
            return
        with response:
            body = response.read()
            self.send_response(response.status)
            self.send_header("Content-Type", response.headers.get("Content-Type", "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5500)
    parser.add_argument("--backend", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    handler = partial(Handler, backend=args.backend, directory=str(Path(__file__).resolve().parent))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Navora: http://127.0.0.1:{args.port}/?api=/api", flush=True)
    server.serve_forever()
