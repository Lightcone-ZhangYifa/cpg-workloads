# Bounded online-only original source acquisition

The original immutable source URL, commit and catalog are unchanged. Run `python run.py probe --output /path/to/fresh-probe` to observe a bounded 256 KiB HTTP prefix and the exact original TAR root. This does not verify the whole input and never yields an offline-material or Dataset qualification.

Run `python run.py acquire --output /path/to/fresh-output --max-bytes YOUR_EXPLICIT_BYTE_BUDGET --max-expanded-bytes YOUR_EXPLICIT_EXPANDED_BUDGET` when ready to obtain the complete original archive. The source tar is retained unchanged under its observed SHA, every regular archive member is hashed without executing source code, and the resolved acquisition lock is written to the receipt. Unknown original SHA/bytes are not silently rewritten into the catalog. This full large-input command has not been locally executed.

The helper acquires original bytes; creating a complete offline CPG package, closing any submodules/external datasets and running dual installation/isolation qualification remain separate maintainer steps. Original notices and licensing metadata apply.
