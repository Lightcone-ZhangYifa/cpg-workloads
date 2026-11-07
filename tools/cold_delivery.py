#!/usr/bin/env python3
"""Fetch explicitly planned original artifacts into a runner's private cache."""
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import release


def delivery_base(value):
    if not isinstance(value, str) or any(c in value for c in "?#\\\r\n\t "):
        raise ValueError("Delivery base must be a credential-free HTTPS origin")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid delivery port") from exc
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in ("", "/")
            or not re.fullmatch(r"[A-Za-z0-9.-]+", parsed.hostname)
            or port is not None and not 1 <= port <= 65535):
        raise ValueError("Delivery base must be a credential-free HTTPS origin")
    return value.rstrip("/")


def fetch(tag, cache):
    plan = release.load_plan(tag)
    if "delivery_base_url" not in plan:
        return False
    base = delivery_base(plan["delivery_base_url"])
    # Validate every record before requesting or disclosing any bytes.
    records = [release.checked_record(checksum) for checksum in plan["artifacts"]]
    if any(record.get("review_policy") != "static-trust-v1" for record in records):
        raise ValueError("Delivery requires an explicit static-trust-v1 review for every artifact")
    for record in records:
        release.source_file({"url": base + "/" + record["sha256"], "sha256": record["sha256"],
                             "bytes": record["bytes"]}, cache, network=True)
    return True


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: cold_delivery.py TAG CACHE")
    cache = Path(sys.argv[2]).absolute()
    if fetch(sys.argv[1], cache):
        with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as output:
            output.write("CPG_DELIVERED_ARTIFACTS=" + str(cache) + "\n")


if __name__ == "__main__":
    main()
