#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Load the installed CA bundle into an SSL context without making connections."""
    import ssl
    bundle = Path(module.where()).resolve()
    require(bundle.is_relative_to(Path(sys.prefix).resolve()) and bundle.is_file(), "CA bundle is outside selected environment")
    content = bundle.read_text("ascii")
    count = content.count("-----BEGIN CERTIFICATE-----")
    require(count > 10 and count == content.count("-----END CERTIFICATE-----"), "CA bundle PEM framing invalid")
    require(module.contents() == content, "CA contents/where mismatch")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(bundle))
    require(context.cert_store_stats()["x509_ca"] > 10, "CA bundle did not load into TLS trust store")
    invalid = work / "invalid.pem"; invalid.write_text("not a certificate")
    raises(ssl.SSLError, lambda: context.load_verify_locations(cafile=str(invalid)), "Malformed PEM was accepted")
    return {"checks": ["selected-environment-bundle", "pem-framing", "contents-identity", "ssl-trust-store-load", "malformed-pem-rejection"], "certificates_in_bundle": count, "network": "not_used"}

if __name__ == "__main__":
    raise SystemExit(main('certifi', 'certifi', functional))
