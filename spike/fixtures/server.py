"""Local fixture server for the compat spike.

Binds to 127.0.0.1 only. Serves static pages from this folder and records every
POST to /submit so tests can verify success server-side.
"""
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

ROOT = Path(__file__).parent
SUBMISSIONS: list[dict] = []
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, body: bytes, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/items":
            items = [{"id": i, "name": f"Item {i}"} for i in range(1, 6)]
            return self._send(200, json.dumps(items).encode(), "application/json")
        if path == "/api/submissions":
            with LOCK:
                return self._send(200, json.dumps(SUBMISSIONS).encode(), "application/json")
        if path == "/api/reset":
            with LOCK:
                SUBMISSIONS.clear()
            return self._send(200, b"ok", "text/plain")
        if path == "/" or path == "":
            path = "/form.html"
        f = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in f.parents or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript",
            ".png": "image/png",
            ".css": "text/css",
        }.get(f.suffix, "application/octet-stream")
        return self._send(200, f.read_bytes(), ctype)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        ctype = self.headers.get("Content-Type", "")
        rec = {"path": self.path, "ctype": ctype.split(";")[0]}
        if ctype.startswith("application/x-www-form-urlencoded"):
            rec["fields"] = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
        elif ctype.startswith("multipart/form-data"):
            text = raw.decode("latin-1")
            rec["multipart_len"] = len(raw)
            rec["has_file"] = 'filename="' in text and 'filename=""' not in text
            fields = {}
            for part in text.split("--" + ctype.split("boundary=")[1])[1:]:
                if 'name="' in part:
                    name = part.split('name="')[1].split('"')[0]
                    if "filename=" not in part:
                        fields[name] = part.split("\r\n\r\n", 1)[-1].rsplit("\r\n", 1)[0]
            rec["fields"] = fields
        elif ctype.startswith("application/json"):
            rec["fields"] = json.loads(raw or b"{}")
        with LOCK:
            SUBMISSIONS.append(rec)
        return self._send(
            200,
            b"<html><head><title>Thanks</title></head><body><main><h1>Application received</h1></main></body></html>",
        )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"fixtures on http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()
