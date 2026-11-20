import http.server
import os
import threading
from functools import partial

class QuietHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # 禁用控制台默认请求访问日志，避免污染测试输出
        pass

class LocalTestServer:
    def __init__(self, directory: str | None = None):
        if directory is None:
            directory = os.path.join(os.path.dirname(__file__), "fixtures")
        self.directory = os.path.abspath(directory)
        self._server = None
        self._thread = None
        self.host = "127.0.0.1"
        self.port = 0

    def start(self) -> None:
        handler = partial(QuietHTTPRequestHandler, directory=self.directory)
        self._server = http.server.ThreadingHTTPServer((self.host, 0), handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None

    def get_url(self, path: str = "/") -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"http://{self.host}:{self.port}{path}"
