import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_server_odoo import config as config_module
from mcp_server_odoo.services.odoo_service import OdooService


class FakeServerProxy:
    """Lightweight XML-RPC stub for smoke testing."""

    def __init__(self, url, **kwargs):
        self.url = url

    def authenticate(self, db, username, password, params):
        return 1

    def version(self):
        return {"server_version": "19.0-mocked"}

    def execute_kw(self, *args, **kwargs):
        return {"ok": True, "args": args, "kwargs": kwargs, "endpoint": self.url}


class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.original_config = config_module.config
        self.original_config_file = os.environ.get("CONFIG_FILE")
        config_module.config = None

    def tearDown(self):
        config_module.config = self.original_config
        if self.original_config_file is not None:
            os.environ["CONFIG_FILE"] = self.original_config_file
        elif "CONFIG_FILE" in os.environ:
            del os.environ["CONFIG_FILE"]

    def test_yaml_config_and_xmlrpc_version_selection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yml"
            config_path.write_text(
                "\n".join(
                    [
                        "odoo:",
                        '  url: "https://example.com"',
                        '  database: "demo"',
                        '  username: "admin"',
                        '  api_key: "token"',
                        '  version: "19.0"',
                        "server:",
                        '  host: "127.0.0.1"',
                        "  port: 8000",
                    ]
                ),
                encoding="utf-8",
            )

            os.environ["CONFIG_FILE"] = str(config_path)
            config_module.config = None
            cfg = config_module.get_config()

            self.assertEqual(cfg.odoo.version, "19.0")

            endpoints = cfg.odoo.get_endpoints()
            self.assertTrue(endpoints["common"].endswith("/xmlrpc/2/common"))
            self.assertTrue(endpoints["object"].endswith("/xmlrpc/2/object"))
            self.assertEqual(endpoints["endpoint_mode"], "xmlrpc2")

            with patch("mcp_server_odoo.services.odoo_service.xmlrpc.client.ServerProxy", FakeServerProxy):
                service = OdooService()
                version_info = service.common.version()
                self.assertEqual(version_info["server_version"], "19.0-mocked")
                self.assertEqual(service.common_endpoint, endpoints["common"])
                self.assertEqual(service.object_endpoint, endpoints["object"])


if __name__ == "__main__":
    unittest.main()
