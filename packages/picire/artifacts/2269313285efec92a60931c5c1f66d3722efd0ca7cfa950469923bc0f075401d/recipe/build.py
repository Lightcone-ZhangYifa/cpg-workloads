#!/usr/bin/env python3
"""Build the pinned Picire source, then prepare relative runtime entry points."""
from pathlib import Path
import subprocess
import sys


def main():
    recipe = Path(__file__).resolve().parent
    subprocess.run([sys.executable, str(recipe / "build_original.py"), *sys.argv[1:]], check=True)
    subprocess.run([sys.executable, str(recipe / "relative_runtime.py"), *sys.argv[1:]], check=True)


if __name__ == "__main__":
    main()
