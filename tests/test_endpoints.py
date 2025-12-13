import os
import tempfile
from pathlib import Path
import unittest

from mcp_server_odoo.config import get_config, config as global_config


class EndpointModeTest(unittest.TestCase):
    def tearDown(self):
        global global_config
        global_config = None
        if "CONFIG_FILE" in os.environ:
            del os.environ["CONFIG_FILE"]

    def test_legacy_xmlrpc_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "config.yml"
            cfg_path.write_text(
                "\n".join(
                    [
                        "odoo:",
                        '  url: "https://example.com"',
                        '  database: "demo"',
                        '  username: "admin"',
                        '  api_key: "token"',
                        '  version: "18.0"',
                        '  endpoint_mode: "xmlrpc"',
                    ]
                ),
                encoding="utf-8",
            )
            os.environ["CONFIG_FILE"] = str(cfg_path)
            cfg = get_config()
            endpoints = cfg.odoo.get_endpoints()
            self.assertTrue(endpoints["common"].endswith("/xmlrpc/common"))
            self.assertTrue(endpoints["object"].endswith("/xmlrpc/object"))
            self.assertEqual(endpoints["endpoint_mode"], "xmlrpc")


if __name__ == "__main__":
    unittest.main()
