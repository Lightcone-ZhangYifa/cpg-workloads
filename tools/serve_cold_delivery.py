#!/usr/bin/env python3
"""Serve only a preselected set of immutable CAS objects on loopback."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import stat

SHA = re.compile(r"[0-9a-f]{64}\Z")


def open_object(directory_fd, checksum, size):
    fd = os.open(checksum + ".cpgpkg.tar.gz", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    file = os.fdopen(fd, "rb")
    try:
        info = os.fstat(file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise ValueError("CAS object is not a regular file of the locked size")
        digest = hashlib.sha256()
        while block := file.read(1024 * 1024):
            digest.update(block)
        if digest.hexdigest() != checksum:
            raise ValueError("CAS object differs from its locked SHA-256")
        file.seek(0)
        return file
    except BaseException:
        file.close()
        raise


def make_handler(directory_fd, allowed):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            checksum = self.path[1:] if self.path.startswith("/") else ""
            if SHA.fullmatch(checksum) is None or checksum not in allowed:
                self.send_error(404)
                return
            try:
                file = open_object(directory_fd, checksum, allowed[checksum])
            except (OSError, ValueError):
                self.send_error(404)
                return
            with file:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(allowed[checksum]))
                self.end_headers()
                while block := file.read(1024 * 1024):
                    self.wfile.write(block)
        def log_message(self, format, *args):
            pass
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cas", type=Path)
    parser.add_argument("allowlist", type=Path, help="JSON mapping SHA-256 to exact byte size")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    allowed = json.loads(args.allowlist.read_text())
    if (not isinstance(allowed, dict) or not allowed or
            any(not isinstance(k, str) or SHA.fullmatch(k) is None or type(v) is not int or v <= 0
                for k, v in allowed.items())):
        raise ValueError("Allowlist must map full SHA-256 values to positive byte sizes")
    fd = os.open(args.cas, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for checksum, size in allowed.items():
            with open_object(fd, checksum, size):
                pass
        with ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(fd, allowed)) as server:
            print(server.server_address[1], flush=True)
            server.serve_forever()
    finally:
        os.close(fd)


if __name__ == "__main__":
    main()
