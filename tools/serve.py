"""Dev server for DinosaurShooter: serves the repo root with no caching, and accepts
POST /shot/<name>.png -> screenshots/<name>.png (used by window.game.snap in the test harness).

    python tools/serve.py [port=8020]
"""
import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "screenshots")


class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".glb": "model/gltf-binary", ".js": "text/javascript"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_POST(self):
        name = os.path.basename(self.path.split("?")[0])
        if not self.path.startswith("/shot/") or not name.endswith(".png"):
            self.send_error(404)
            return
        os.makedirs(SHOTS, exist_ok=True)
        with open(os.path.join(SHOTS, name), "wb") as f:
            f.write(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


port = int(sys.argv[1]) if len(sys.argv) > 1 else 8020
print(f"DinosaurShooter on http://localhost:{port}", flush=True)
ThreadingHTTPServer(("", port), partial(Handler, directory=ROOT)).serve_forever()
