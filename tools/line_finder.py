"""Team builder + line finder page: drag units onto a hex board, put items on them, pick augments; see every
Set 19 meta comp by tier with its openers, midgame boards, +1 units, unlocks, endgame itemization and the
conditions you meet. Icons from tools/fetch_icons.py (run it once).

    python3 -I tools/line_finder.py [--port 8766]          then open http://127.0.0.1:8766

A static reference like tftflow: manual input only, nothing read from the game (docs/POLICY.md). The server
listens on 127.0.0.1 only; MetaTFT-derived data stays on this machine (ToS 6.1). The page builds every
element with DOM methods (text nodes only), so names from the data can't inject markup.
"""
import json
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "engine"), str(ROOT / "tools")]
import linefinder  # noqa: E402
from unlocks import load_set  # noqa: E402

PAGE = (Path(__file__).resolve().parent / "line_finder.html")


def main():
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8766
    static = load_set("TFTSet19")
    cat = linefinder.catalog(static)
    catalog = json.dumps(cat).encode()
    icons = {f"/icons/{path}": ROOT / "data" / "assets" / "icons" / path for kind in cat["icons"].values() for path in kind.values()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, body, kind="application/json", code=200):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self.send(PAGE.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/catalog":
                self.send(catalog)
            elif urllib.parse.unquote(self.path) in icons:            # only files listed in the icon index
                f = icons[urllib.parse.unquote(self.path)]
                self.send(f.read_bytes(), "image/png") if f.exists() else self.send(b"{}", code=404)
            else:
                self.send(b"{}", code=404)

        def do_POST(self):
            if self.path != "/api/find":
                return self.send(b"{}", code=404)
            n = int(self.headers.get("Content-Length") or 0)
            if n > 100_000:
                return self.send(b'{"error":"too large"}', code=413)
            try:
                inp = json.loads(self.rfile.read(n) or b"{}")
                self.send(json.dumps(linefinder.find(static, inp)).encode())
            except (ValueError, KeyError, TypeError) as e:
                self.send(json.dumps({"error": str(e)}).encode(), code=400)
            except Exception as e:                       # noqa: BLE001 -- answer instead of dropping the connection
                import traceback
                traceback.print_exc()
                self.send(json.dumps({"error": f"internal error: {type(e).__name__}"}).encode(), code=500)

    print(f"open http://127.0.0.1:{port}  (Ctrl-C to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
