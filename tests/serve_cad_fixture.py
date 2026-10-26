# SPDX-License-Identifier: LGPL-2.1-or-later
"""Local, isolated static server for the real WASM workspace test."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import sys


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cross-Origin-Opener-Policy', 'same-origin')
        self.send_header('Cross-Origin-Embedder-Policy', 'require-corp')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def do_POST(self):
        self.send_response(204)
        self.end_headers()


if __name__ == '__main__':
    handler = functools.partial(Handler, directory=sys.argv[1])
    ThreadingHTTPServer(('127.0.0.1', int(sys.argv[2])), handler).serve_forever()
