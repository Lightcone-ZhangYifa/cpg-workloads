# CSiBE online-only acquisition

This is an acquisition recipe, not a qualified offline CPG package. The complete original main archive is pinned and verified, but CMSIS exceeds the local download budget. The original sources and catalog facts remain unchanged. Both direct submodule commits are explicitly recorded; nested submodules are resolved by Git from these fixed commits when the owner performs full acquisition.

Use `python run.py probe --output /path/to/fresh-probe` for a bounded 64 KiB HTTP prefix observation per direct submodule. This never claims full archive identity. Use `python run.py acquire --allow-large-recursive --output /path/to/fresh-output` for the complete original main archive and a Git checkout at the original commit with recursive pinned submodules. The large full acquisition was not executed locally.

The latter retains Git metadata, logs and a receipt; it does not run corpus code, modify system packages, create a qualified offline CPG artifact, qualify a Dataset interface, or produce an official benchmark score. Full material packaging and lifecycle verification are still required. Original license labels and notices apply.
