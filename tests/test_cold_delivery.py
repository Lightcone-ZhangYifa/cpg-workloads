#!/usr/bin/env python3
import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import cold_delivery
import release
import serve_cold_delivery as server


class Response(io.BytesIO):
    def __init__(self, data, url="https://delivery.example/asset"):
        super().__init__(data)
        self.url = url
    def geturl(self):
        return self.url


class DeliveryTests(unittest.TestCase):
    def test_url_scope(self):
        self.assertEqual(cold_delivery.delivery_base("https://example.org/"), "https://example.org")
        for url in ("http://example.org", "https://user@example.org", "https://example.org/path",
                    "https://example.org/?x=1", "https://example.org/#fragment", "https://example.org/%2e%2e",
                    "https://example.org\\evil", "https://example.org:99999"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                cold_delivery.delivery_base(url)

    def test_absent_field_noop_and_scope_checked_before_network(self):
        with patch.object(release, "load_plan", return_value={"artifacts": ["a" * 64]}), \
             patch.object(release, "source_file") as get:
            self.assertFalse(cold_delivery.fetch("tag", Path("unused")))
            get.assert_not_called()
        plan = {"delivery_base_url": "https://example.org", "artifacts": ["a" * 64, "b" * 64]}
        records = [{"sha256": "a" * 64, "bytes": 3, "review_policy": "static-trust-v1"},
                   {"sha256": "b" * 64, "bytes": 4, "review_policy": "other"}]
        with patch.object(release, "load_plan", return_value=plan), \
             patch.object(release, "checked_record", side_effect=records), \
             patch.object(release, "source_file") as get:
            with self.assertRaises(ValueError): cold_delivery.fetch("tag", Path("unused"))
            get.assert_not_called()

    def test_exact_bytes_and_reject_size_hash_and_unsafe_redirect(self):
        content = b"original bytes"
        checksum = hashlib.sha256(content).hexdigest()
        plan = {"delivery_base_url": "https://example.org", "artifacts": [checksum]}
        record = {"sha256": checksum, "bytes": len(content), "review_policy": "static-trust-v1"}
        with tempfile.TemporaryDirectory() as temp, patch.object(release, "load_plan", return_value=plan), \
             patch.object(release, "checked_record", return_value=record):
            for index, response in enumerate((Response(content), Response(content + b"x"),
                                               Response(b"x" * len(content)), Response(content, "http://unsafe/"))):
                with patch.object(release, "urlopen", return_value=response) as get:
                    cache = Path(temp) / str(index)
                    if index == 0:
                        self.assertTrue(cold_delivery.fetch("tag", cache))
                        self.assertEqual((cache / checksum).read_bytes(), content)
                        self.assertEqual(get.call_args.args[0], "https://example.org/" + checksum)
                    else:
                        with self.assertRaises(ValueError): cold_delivery.fetch("tag", cache)
                        self.assertFalse((cache / checksum).exists())

    def test_server_only_allowlisted_regular_files(self):
        content = b"public object"
        checksum = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / (checksum + ".cpgpkg.tar.gz")).write_bytes(content)
            secret = root / "secret"
            secret.write_bytes(b"private")
            other = hashlib.sha256(b"private").hexdigest()
            (root / (other + ".cpgpkg.tar.gz")).symlink_to(secret)
            fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            self.addCleanup(os.close, fd)
            with self.assertRaises(OSError): server.open_object(fd, other, 7)
            with ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(fd, {checksum: len(content)})) as http:
                thread = threading.Thread(target=http.serve_forever, daemon=True)
                thread.start()
                base = "http://127.0.0.1:" + str(http.server_address[1])
                try:
                    with urlopen(base + "/" + checksum) as response:
                        self.assertEqual(response.read(), content)
                    for path in ("/", "/secret", "/../secret", "/%2e%2e/secret", "/" + other,
                                 "/" + checksum + "?x=1"):
                        with self.subTest(path=path), self.assertRaises(HTTPError) as caught:
                            urlopen(base + path)
                        self.assertEqual(caught.exception.code, 404)
                finally:
                    http.shutdown()
                    thread.join()


if __name__ == "__main__":
    unittest.main()
