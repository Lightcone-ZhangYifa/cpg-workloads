# Original artifact delivery

A release plan may set `delivery_base_url` to a credential-free HTTPS origin to
supply its explicitly listed, statically reviewed original artifacts. The runner
requests only `/<sha256>` for each listed artifact and verifies its full SHA-256
and catalog byte size before the existing publication path accepts it. Plans
without this field are unchanged. The endpoint may be temporary; the immutable
GitHub Release assets and verified publication receipts are the canonical public
downloads. An expired endpoint can prevent a new run, but never changes a plan or
an already published asset.

For a local CAS delivery, `tools/serve_cold_delivery.py CAS ALLOWLIST` accepts a
JSON map of explicitly authorized SHA-256 values to their exact byte sizes. It
binds only to loopback, serves only corresponding ordinary CAS files, and checks
all byte locks before serving. An independently configured HTTPS tunnel can
expose that server for the duration of an authorized public release. Never put
credentials in the committed URL or include non-public objects in the allowlist.
