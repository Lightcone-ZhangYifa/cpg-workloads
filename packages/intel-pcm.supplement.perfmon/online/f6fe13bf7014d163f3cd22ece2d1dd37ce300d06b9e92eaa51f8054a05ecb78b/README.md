# Locked complete-original material recipe

Install compiler-playground 0.21.8, then run:

    python3 recipe/prepare.py --cache /path/to/cache --output /path/to/new.cpgpkg.tar.gz

The unchanged shared CPG acquisition API fetches the complete original input and verifies its exact SHA-256 and size.
Use `--no-network` to require an existing verified cache. No input payload is embedded in this recipe archive.
This release verified cache reconstruction against the exact offline package. Live-origin HTTPS retrieval was not repeated.
No native execution, OCI, Dataset, hardware or official benchmark qualification is implied.
