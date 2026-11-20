import unittest
import urllib.request
import os
import sys

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
parent_dir = os.path.dirname(repo_root)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from tests.e2e.server import LocalTestServer

class TestLocalTestServer(unittest.TestCase):
    def test_server_serves_fixtures(self):
        server = LocalTestServer()
        server.start()
        try:
            url = server.get_url("/test_page.html")
            with urllib.request.urlopen(url) as response:
                self.assertEqual(response.status, 200)
                content = response.read().decode("utf-8")
                self.assertIn("Playwright Tools E2E Test Page", content)
        finally:
            server.stop()
