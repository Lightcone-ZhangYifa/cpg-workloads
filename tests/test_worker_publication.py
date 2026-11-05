"""Publication regressions using the actual audited worker 011 material master.

No GitHub requests are made. Archive bytes, qualification logs and local Git
state are real; only the remote GitHub boundary is simulated.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

SOURCE_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("worker_publication", SOURCE_ROOT / "tools/publish_workers.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)

SHA = "050720b9f7b9095d878996dc014f7ab68f411fe1f0be3e9695a19cad04c40b38"
PACKAGE_BYTES = 287072
TAG = "worker-011-publication-regression"
COMMIT = "1" * 40


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


class GitHubBoundary:
    """The GitHub responses needed by publish, retaining actual uploaded bytes."""

    def __init__(self, *, existing=False):
        self.release = self._release() if existing else None
        self.assets = {}
        self.uploads = {}
        self.writes = []
        self.tag_exists = existing

    @staticmethod
    def _release():
        return {"id": 7311, "tag_name": TAG, "target_commitish": COMMIT,
                "draft": True, "published_at": None,
                "html_url": f"https://github.com/{publisher.REPOSITORY}/releases/tag/{TAG}"}

    def __call__(self, *args, missing=False):
        if args[0] == "api":
            endpoint = args[1]
            if endpoint.endswith("/releases/tags/" + TAG):
                return copy.deepcopy(self.release)
            if endpoint.endswith("/git/ref/tags/" + TAG):
                return {"object": {"type": "commit", "sha": COMMIT}} if self.tag_exists else None
            if "/releases/7311/assets?" in endpoint:
                return list(copy.deepcopy(self.assets).values())
            raise AssertionError("Unexpected remote read: " + repr(args))
        self.writes.append(args)
        if args[:2] == ("release", "create"):
            if args[args.index("--target") + 1] != COMMIT or self.release is not None:
                raise AssertionError("Unexpected release creation")
            self.release = self._release()
            return self.release["html_url"]
        if args[:2] == ("release", "upload"):
            path = Path(args[-1])
            raw = path.read_bytes()
            if path.name in self.assets:
                raise AssertionError("An existing asset was overwritten")
            self.uploads[path.name] = raw
            self.assets[path.name] = {"name": path.name, "state": "uploaded", "size": len(raw),
                                      "digest": "sha256:" + hashlib.sha256(raw).hexdigest()}
            return ""
        if args[:2] == ("release", "edit") and "--draft=false" in args:
            self.release.update(draft=False, published_at="2026-11-05T00:00:00Z")
            self.tag_exists = True
            return ""
        raise AssertionError("Unexpected remote write: " + repr(args))


class WorkerPublication(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="cpg-worker-publication-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "repository"
        self.root.mkdir()
        self.record_path = self.root / "catalog/artifacts" / (SHA + ".json")
        source_record = SOURCE_ROOT / "catalog/artifacts" / (SHA + ".json")
        self.record = json.loads(source_record.read_text())
        write_json(self.record_path, self.record)
        self.template = self.root / self.record["template"]
        shutil.copytree(SOURCE_ROOT / self.record["template"], self.template)
        write_json(self.root / "release-plans/workers" / (TAG + ".json"),
                   {"kind": "cpg_worker_release_plan", "tag": TAG, "artifacts": [SHA]})
        write_json(self.root / "manifest.json", {
            "schema_version": 1, "kind": "compiler_playground_package_repository",
            "packages": [], "online_recipes": [], "releases": [],
            "policy": {"historical_resource_denominator": 1862},
        })
        self.patch_root = mock.patch.object(publisher, "ROOT", self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.environment = mock.patch.dict(os.environ, {
            "GITHUB_SHA": COMMIT, "GITHUB_REPOSITORY": publisher.REPOSITORY,
            "GITHUB_REF_NAME": "publish-workers/" + TAG,
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def reject_before_remote_write(self, message):
        output = self.base / "rejected-output"
        with mock.patch.object(publisher, "gh") as remote:
            with self.assertRaisesRegex(ValueError, message):
                publisher.publish(TAG, output)
            remote.assert_not_called()
        self.assertFalse((output / "publication.json").exists())

    def publish_to_boundary(self):
        boundary = GitHubBoundary()
        output = self.base / "publication"
        with mock.patch.object(publisher, "gh", boundary), mock.patch.object(publisher, "frozen"):
            with contextlib.redirect_stdout(io.StringIO()):
                publisher.publish(TAG, output)
        return boundary, output, json.loads((output / "publication.json").read_text())

    def test_real_material_replays_to_exact_cpg_bytes_twice(self):
        outputs = [self.base / "first", self.base / "second"]
        archives = []
        for output in outputs:
            value, assets, _ = publisher.build(TAG, output)
            self.assertEqual(len(value["packages"]), 1)
            package = next(path for path in assets if path.name.endswith(".cpgpkg.tar.gz"))
            raw = package.read_bytes()
            self.assertEqual(len(raw), PACKAGE_BYTES)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), SHA)
            archives.append(raw)
        self.assertEqual(archives[0], archives[1])

    def test_changed_payload_blocks_publication(self):
        source = self.template / "payload/materials/upstream/llvm/docs/Remarks.rst"
        source.write_bytes(source.read_bytes() + b"\nUnreviewed mutation\n")
        self.reject_before_remote_write("Master member differs")

    def test_changed_qualification_log_blocks_publication(self):
        result = next(row for row in self.record["qualification"]["checks"]["results"]
                      if row["kind"] == "functional")
        path = self.template / result["stdout"]["retained_path"]
        path.write_bytes(path.read_bytes() + b"\nUnreviewed result\n")
        self.reject_before_remote_write("Retained installation/check log differs")

    def test_missing_functional_log_is_not_accepted_as_evidence(self):
        result = next(row for row in self.record["qualification"]["checks"]["results"]
                      if row["kind"] == "functional")
        result.pop("stdout")
        write_json(self.record_path, self.record)
        with self.assertRaises(ValueError):
            publisher.build(TAG, self.base / "missing-log")

    def test_failed_functional_detail_overrides_passed_aggregate_claim(self):
        result = next(row for row in self.record["qualification"]["checks"]["results"]
                      if row["kind"] == "functional")
        result.update(status="failed", returncode=1)
        write_json(self.record_path, self.record)
        self.reject_before_remote_write("Declared software check did not pass")

    def test_existing_partial_file_is_not_overwritten_or_deleted(self):
        record, manifest = publisher.artifact(SHA)
        output = self.base / "existing-partial"
        output.mkdir()
        partial = output / (record["asset_name"] + ".part")
        partial.write_bytes(b"Owned by another invocation\n")
        with self.assertRaises(FileExistsError):
            publisher.replay(record, manifest, output)
        self.assertEqual(partial.read_bytes(), b"Owned by another invocation\n")

    def test_existing_remote_mismatch_or_extra_asset_is_never_replaced(self):
        cases = ("wrong-digest", "wrong-size", "extra-asset")
        for case in cases:
            with self.subTest(case=case):
                output = self.base / case
                _, assets, _ = publisher.build(TAG, output)
                package = next(path for path in assets if path.name.endswith(".cpgpkg.tar.gz"))
                boundary = GitHubBoundary(existing=True)
                boundary.assets[package.name] = {
                    "name": package.name, "state": "uploaded", "size": PACKAGE_BYTES,
                    "digest": "sha256:" + SHA,
                }
                if case == "wrong-digest":
                    boundary.assets[package.name]["digest"] = "sha256:" + "0" * 64
                elif case == "wrong-size":
                    boundary.assets[package.name]["size"] += 1
                else:
                    boundary.assets["unreviewed.txt"] = {
                        "name": "unreviewed.txt", "state": "uploaded", "size": 1,
                        "digest": "sha256:" + hashlib.sha256(b"x").hexdigest(),
                    }
                with mock.patch.object(publisher, "gh", boundary), mock.patch.object(publisher, "frozen"):
                    with self.assertRaisesRegex(ValueError, "Remote (asset|release asset set)"):
                        publisher.publish(TAG, output)
                self.assertEqual(boundary.writes, [])
                self.assertFalse((output / "publication.json").exists())

    def test_receipt_and_catalog_bind_the_exact_uploaded_manifest(self):
        boundary, output, receipt = self.publish_to_boundary()
        self.assertEqual(set(boundary.uploads), {self.record["asset_name"], "manifest.json", "SHA256SUMS"})
        self.assertEqual(boundary.uploads[self.record["asset_name"]],
                         (output / self.record["asset_name"]).read_bytes())
        uploaded_manifest = boundary.uploads["manifest.json"]
        identity = receipt["release"]["verified_assets"]["manifest.json"]
        self.assertEqual(identity, {"bytes": len(uploaded_manifest),
                                   "sha256": hashlib.sha256(uploaded_manifest).hexdigest()})
        self.assertEqual(json.loads(uploaded_manifest)["packages"], receipt["packages"])
        self.assertTrue(receipt["release"]["published"])
        publisher.record_publication(output / "publication.json")
        root_manifest = json.loads((self.root / "manifest.json").read_text())
        self.assertEqual(root_manifest["packages"], receipt["packages"])
        self.assertEqual(root_manifest["policy"]["historical_resource_denominator"], 1862)
        self.assertEqual(root_manifest["online_recipes"], [])
        first = (self.root / "manifest.json").read_bytes()
        publisher.record_publication(output / "publication.json")
        self.assertEqual((self.root / "manifest.json").read_bytes(), first)

    def test_receipt_cannot_rebind_source_commit_or_uploaded_checksums(self):
        _, _, receipt = self.publish_to_boundary()
        changed_commit = copy.deepcopy(receipt)
        changed_commit["release"]["source_commit"] = "2" * 40
        with self.assertRaisesRegex(ValueError, "Receipt is not bound to the uploaded manifest"):
            publisher.validate_receipt(changed_commit)
        changed_checksums = copy.deepcopy(receipt)
        changed_checksums["release"]["verified_assets"]["SHA256SUMS"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "Receipt is not bound to the uploaded checksums"):
            publisher.validate_receipt(changed_checksums)

    def test_gh_release_create_accepts_plain_stdout_and_api_decodes_json(self):
        release_url = f"https://github.com/{publisher.REPOSITORY}/releases/tag/{TAG}"
        result = subprocess.CompletedProcess(["gh"], 0, stdout=release_url + "\n", stderr="")
        with mock.patch.object(publisher.subprocess, "run", return_value=result):
            self.assertEqual(publisher.gh("release", "create", TAG), release_url)
        result = subprocess.CompletedProcess(["gh"], 0, stdout='{"id": 7311}\n', stderr="")
        with mock.patch.object(publisher.subprocess, "run", return_value=result):
            self.assertEqual(publisher.gh("api", "repos/example/releases/7311"), {"id": 7311})

    def test_frozen_rejects_real_git_head_mismatch_and_dirty_master(self):
        def git(*args):
            return subprocess.run(["git", *args], cwd=self.root, text=True,
                                  capture_output=True, check=True).stdout.strip()
        git("init", "-q", "-b", "main")
        git("config", "user.name", "Publication Regression")
        git("config", "user.email", "publication-regression@example.invalid")
        git("add", ".")
        git("commit", "-q", "-m", "Freeze the audited material fixture")
        head = git("rev-parse", "HEAD")
        with self.assertRaisesRegex(ValueError, "checkout differs"):
            publisher.frozen("0" * 40, [self.record["template"]])
        source = self.template / "payload/materials/upstream/llvm/docs/Remarks.rst"
        source.write_bytes(source.read_bytes() + b"\nUncommitted input\n")
        self.assertIn("Remarks.rst", git("status", "--porcelain"))
        with self.assertRaisesRegex(ValueError, "uncommitted changes"):
            publisher.frozen(head, [self.record["template"]])


if __name__ == "__main__":
    unittest.main(verbosity=2)
