"""Local browser discovery must not be routed through a system proxy."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from tools.cdp_browser import CDPBrowserManager


class LocalDiscoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_bypasses_proxy(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != '/json/version':
                    self.send_error(404)
                    return
                body = json.dumps({'webSocketDebuggerUrl': 'ws://localhost/browser-test'}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.dict('os.environ', {
                'HTTP_PROXY': 'http://127.0.0.1:1',
                'HTTPS_PROXY': 'http://127.0.0.1:1',
                'ALL_PROXY': 'http://127.0.0.1:1',
                'NO_PROXY': '', 'no_proxy': '',
            }):
                result = await CDPBrowserManager()._get_browser_websocket_url(server.server_port)
            self.assertEqual(result, 'ws://localhost/browser-test')
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == '__main__':
    unittest.main()
