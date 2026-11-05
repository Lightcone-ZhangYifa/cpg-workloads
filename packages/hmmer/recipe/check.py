#!/usr/bin/env python3
"""Validate HMMER biological workflows using installed binaries and retained fixtures."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    args = parser.parse_args()
    prefix = args.prefix.resolve()
    args.build.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="hmmer-functional-", dir=args.build))
    source = prefix / "share/hmmer/source"
    environment = dict(os.environ)
    for name in ("LD_PRELOAD", "LD_LIBRARY_PATH", "HMMERDB", "BLASTDB"):
        environment.pop(name, None)
    environment.update(PATH="/usr/bin:/bin", LC_ALL="C", HMMER_NCPU="1")
    report = {"resource": "hmmer", "status": "running", "prefix": str(prefix), "commands": [],
              "functional_assertions": [], "negative_checks": []}

    def run(label, name, arguments, *, negative=None):
        argv = [str(prefix / "bin" / name), *map(str, arguments)]
        result = subprocess.run(argv, cwd=work, env=environment, capture_output=True, timeout=120)
        (work / (label + ".stdout")).write_bytes(result.stdout)
        (work / (label + ".stderr")).write_bytes(result.stderr)
        row = {"label": label, "argv": argv, "returncode": result.returncode,
               "stdout": label + ".stdout", "stderr": label + ".stderr"}
        report["commands"].append(row)
        text = (result.stdout + result.stderr).decode(errors="replace")
        if negative:
            if result.returncode == 0 or negative.lower() not in text.lower():
                raise AssertionError("Invalid input was not rejected with the expected diagnostic: " + label)
            report["negative_checks"].append({**row, "diagnostic": negative})
        elif result.returncode != 0:
            raise RuntimeError("Installed HMMER workflow failed: " + label + ": " + text)
        return result.stdout.decode(errors="replace")

    try:
        help_text = run("version", "hmmbuild", ["-h"])
        if "HMMER 3.4" not in help_text:
            raise AssertionError("Installed HMMER version differs from source identity")
        alignment, query = source / "tutorial/globins4.sto", source / "tutorial/HBB_HUMAN"
        fixtures = [{"path": str(p.relative_to(prefix)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size} for p in (alignment, query)]
        model = work / "globins.hmm"
        run("build-profile", "hmmbuild", ["--amino", "--cpu", "1", "--seed", "42", model, alignment])
        text = model.read_text()
        if not text.startswith("HMMER3/") or "NAME  globins4" not in text or "ALPH  amino" not in text:
            raise AssertionError("Generated protein profile is malformed")
        run("search-sequence", "hmmsearch", ["--cpu", "1", "--tblout", work / "search.tbl", model, query])
        search = [line.split() for line in (work / "search.tbl").read_text().splitlines() if line.strip() and not line.startswith("#")]
        if len(search) != 1 or search[0][0] != "HBB_HUMAN" or search[0][2] != "globins4" or float(search[0][4]) >= 1e-5 or float(search[0][5]) <= 20:
            raise AssertionError("The human beta-globin target was not recovered with strong model support")
        report["functional_assertions"].append({"name": "profile-build-and-homology-search", "fixtures": fixtures,
                                               "target": search[0][0], "query_profile": search[0][2], "evalue": search[0][4], "score": search[0][5]})
        aligned = run("align-sequence", "hmmalign", ["--outformat", "Stockholm", model, query])
        sequence = "".join(line.strip() for line in query.read_text().splitlines() if not line.startswith(">"))
        aligned_sequence = "".join(line.split()[1] for line in aligned.splitlines() if line.startswith("HBB_HUMAN "))
        decoded = "".join(char for char in aligned_sequence if char.isalpha()).upper()
        if not aligned.startswith("# STOCKHOLM 1.0") or decoded != sequence.upper():
            raise AssertionError("Profile alignment changed or omitted the original sequence")
        report["functional_assertions"].append({"name": "sequence-preserving-profile-alignment", "residues": len(sequence)})
        run("press-database", "hmmpress", [model])
        index_files = [Path(str(model) + suffix) for suffix in (".h3f", ".h3i", ".h3m", ".h3p")]
        if not all(path.is_file() and path.stat().st_size > 0 for path in index_files):
            raise AssertionError("The indexed profile database is incomplete")
        run("scan-profile-database", "hmmscan", ["--cpu", "1", "--tblout", work / "scan.tbl", model, query])
        scan = [line.split() for line in (work / "scan.tbl").read_text().splitlines() if line.strip() and not line.startswith("#")]
        if len(scan) != 1 or (scan[0][0], scan[0][2]) != ("globins4", "HBB_HUMAN") or float(scan[0][4]) >= 1e-5:
            raise AssertionError("Indexed model scanning did not recover the expected profile")
        report["functional_assertions"].append({"name": "indexed-profile-scan", "index_files": len(index_files), "model": scan[0][0], "evalue": scan[0][4]})
        fasta = run("easel-alignment-conversion", "esl-reformat", ["fasta", alignment])
        if sum(line.startswith(">") for line in fasta.splitlines()) != 4:
            raise AssertionError("Easel did not convert all four original alignment members")
        report["functional_assertions"].append({"name": "easel-stockholm-to-fasta", "sequences": 4})
        (work / "bad.hmm").write_text("This is not an HMM profile\n")
        (work / "bad.alignment").write_text("This is not an alignment\n")
        run("reject-malformed-model", "hmmsearch", [work / "bad.hmm", query], negative="format")
        run("reject-malformed-alignment", "hmmbuild", [work / "bad-output.hmm", work / "bad.alignment"], negative="format")
        run("reject-unknown-option", "hmmsearch", ["--cpg-invalid-option"], negative="option")
        profile = json.loads((prefix / "share/compiler-playground/hmmer/profile.json").read_text())
        if profile["upstream_tests"]["status"] != "passed" or profile["upstream_tests"]["executed"] < 100:
            raise AssertionError("The packaged source build omitted its actual selected upstream native tests")
        supplement = prefix / "share/hmmer/supplements" / profile["supplement"]["filename"]
        if hashlib.sha256(supplement.read_bytes()).hexdigest() != profile["supplement"]["sha256"]:
            raise AssertionError("Retained supplemental source distribution changed")
        report.update(status="passed", positive_workflows=4, negative_cli_checks=3,
                      upstream_tests_for_packaged_build=profile["upstream_tests"]["executed"])
    except Exception as error:
        report.update(status="failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        (work / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
