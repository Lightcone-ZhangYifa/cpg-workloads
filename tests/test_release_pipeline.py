#!/usr/bin/env python3
"""Regression tests for publication gates, retained evidence and rolling imports."""
from __future__ import annotations

import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import import_archives as importer
import release
import validate_repository as validator


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix="cpg-release-test-")
        self.addCleanup(self.scratch.cleanup)
        self.work = Path(self.scratch.name)
        self.root = self.work / "repository"
        self.root.mkdir()
        importer.write_json(self.root / "manifest.json", {"packages": []})
        self.record = json.loads((ROOT / "tests/fixtures/release-wrapper/record.json").read_text())
        self.manifest = json.loads((ROOT / "tests/fixtures/release-wrapper/manifest.json").read_text())
        self.template = self.root / self.record["template"]
        self.template.mkdir(parents=True)
        importer.write_json(self.template / "manifest.json", self.manifest)
        importer.write_json(self.root / "catalog/artifacts" / (self.record["sha256"] + ".json"), self.record)
        self.root_patch = patch.object(release, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def plan(self, tag="apt-001"):
        value = {"schema_version": 1, "kind": "cpg_workload_release_plan", "repository": release.REPOSITORY,
                 "tag": tag, "artifacts": [self.record["sha256"]]}
        importer.write_json(self.root / "release-plans" / (tag + ".json"), value)
        return value

    def published(self, tag="apt-001"):
        self.plan(tag)
        with patch.dict(os.environ, {"GITHUB_SHA": "a" * 40}):
            _, value, paths = release.build_plan(tag, self.work / tag, network=False)
        value["release"].update(published=True, asset_count=len(paths),
            url=f"https://github.com/{release.REPOSITORY}/releases/tag/{tag}", release_id=5,
            published_at="2026-11-05T00:00:00Z", verified_assets={
                p.name: {"sha256": importer.sha256(p), "bytes": p.stat().st_size} for p in paths})
        return value

    def nonapt(self):
        manifest, record = copy.deepcopy(self.manifest), copy.deepcopy(self.record)
        spec = manifest["package"]
        spec.update(id="test.functional", provider="local")
        spec["recipe"] = {"manager": "source"}
        spec["checks"] = [{"id": "compute", "kind": "functional", "expected_returncode": 0,
                           "argv": [sys.executable, "-c", "print(6*7)"], "stdout_regex": "42"}]
        manifest["method"] = "source"
        record.update(id=spec["id"], method="source", functional="not_run", release_eligible=False)
        stdout, stderr = self.work / "run.out", self.work / "run.err"
        with stdout.open("wb") as out, stderr.open("wb") as err:
            result = subprocess.run(spec["checks"][0]["argv"], stdout=out, stderr=err, check=True)
        log = lambda p: {"path": str(p), "sha256": importer.sha256(p), "bytes": p.stat().st_size}
        receipt = {"status": "installed", "installation": {"status": "installed", "evidence": []},
                   "package_artifact": {"sha256": record["sha256"], "bytes": record["bytes"]},
                   "checks": {"functional_status": "passed", "results": [{**spec["checks"][0],
                        "status": "passed", "returncode": result.returncode, "timed_out": False,
                        "stdout": log(stdout), "stderr": log(stderr)}]}}
        importer.record_installation(record, receipt, self.template)
        return manifest, record, receipt

    def test_original_wrapper_rebuild_is_byte_identical(self):
        result = release.rebuild(self.record, self.work / "output", self.work / "cache")
        self.assertEqual(importer.sha256(result), self.record["sha256"])
        self.assertEqual(result.stat().st_size, self.record["bytes"])
        self.assertEqual(result.name, self.record["asset_name"])
        with tarfile.open(result) as archive:
            self.assertEqual(json.load(archive.extractfile("manifest.json")), self.manifest)

    def test_record_publication_keeps_canonical_receipt_immutable(self):
        value = self.published()
        source = self.work / "receipt.json"
        importer.write_json(source, value)
        relative = release.record_publication(source)
        self.assertEqual(relative, Path("catalog/releases/apt-001.json"))
        self.assertEqual(release.record_publication(source), relative)
        value["release"]["release_id"] += 1
        importer.write_json(source, value)
        with self.assertRaisesRegex(ValueError, "immutable"):
            release.record_publication(source)

    def test_record_publication_indexes_historical_bytes_separately(self):
        record = copy.deepcopy(self.record)
        record["index_role"] = "historical-snapshot"
        origin = {"archive": "delivery.zip", "sha256": "b" * 64,
                  "bytes": 100, "member": "original.cpgpkg.tar.gz"}
        record.setdefault("origins", []).append(origin)
        artifact = {key: record[key] for key in (
            "id", "version", "build", "method", "target", "sha256", "bytes", "manifest_sha256")}
        descriptor = {"schema_version": 1, "kind": "cpg_historical_snapshot",
                      "selection": "explicit_sha256_only", "dependency_profile_qualified": False,
                      "artifact": artifact, "origin": origin,
                      "context": {"kind": "original-delivery-member",
                                  "sha256": release.digest({"artifact": artifact, "origin": origin})}}
        importer.write_json(self.root / "catalog/artifacts" / (record["sha256"] + ".json"), record)
        importer.write_json(self.root / "catalog/historical-snapshots" / (record["sha256"] + ".json"), descriptor)
        value = self.published("historical-001")
        source = self.work / "historical.json"
        importer.write_json(source, value)
        self.assertEqual(release.record_publication(source),
                         Path("catalog/historical-releases/historical-001.json"))
        index = release.merge_manifest()
        self.assertEqual(index["packages"], [])
        self.assertEqual([row["sha256"] for row in index["historical_snapshots"]], [record["sha256"]])

    def test_changed_manifest_inventory_is_rejected(self):
        value = copy.deepcopy(self.manifest)
        value["package"]["version"] += "tampered"
        importer.write_json(self.template / "manifest.json", value)
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            release.checked_record(self.record["sha256"])

    def test_existing_release_bytes_cannot_be_overwritten(self):
        output = self.work / "output"
        output.mkdir()
        destination = output / self.record["asset_name"]
        destination.write_bytes(b"do not overwrite")
        with self.assertRaises(FileExistsError):
            release.rebuild(self.record, output, self.work / "cache")
        self.assertEqual(destination.read_bytes(), b"do not overwrite")

    def test_rebuild_does_not_delete_another_attempt_partial(self):
        output = self.work / "output"
        output.mkdir()
        other = output / (self.record["asset_name"] + ".part")
        other.write_bytes(b"another attempt")
        release.rebuild(self.record, output, self.work / "cache")
        self.assertEqual(other.read_bytes(), b"another attempt")

    def test_rebuild_reuses_verified_archive(self):
        output = self.work / "output"
        first = release.rebuild(self.record, output, self.work / "cache")
        before = first.stat().st_mtime_ns
        self.assertEqual(release.rebuild(self.record, output, self.work / "cache"), first)
        self.assertEqual(first.stat().st_mtime_ns, before)

    def test_only_apt_wrapper_can_use_exemption(self):
        value = copy.deepcopy(self.manifest)
        value["package"]["provider"] = "pip"
        self.assertTrue(any("Only exactly rebuilt APT" in s for s in importer.qualification_errors(self.record, value)))
        record = {**self.record, "reproduced_sha256": "0" * 64}
        self.assertTrue(importer.qualification_errors(record, self.manifest))

    def test_actual_functional_logs_survive_temporary_prefix_cleanup(self):
        manifest, record, receipt = self.nonapt()
        self.assertEqual(importer.installation_errors(record, manifest["package"]), [])
        (self.work / "run.out").unlink()
        (self.work / "run.err").unlink()
        release.verify_evidence(record, self.template)
        retained = record["qualification"]["checks"]["results"][0]["stdout"]["retained_path"]
        self.assertEqual((self.template / retained).read_text(), "42\n")
        self.assertNotIn("retained_path", receipt["checks"]["results"][0]["stdout"])

    def test_passing_label_without_execution_evidence_is_rejected(self):
        manifest, record, _ = self.nonapt()
        record["qualification"]["checks"]["results"][0].pop("stdout")
        self.assertTrue(any("retained stdout" in s for s in importer.installation_errors(record, manifest["package"])))

    def test_tampered_retained_functional_log_is_rejected(self):
        _, record, _ = self.nonapt()
        log = record["qualification"]["checks"]["results"][0]["stdout"]
        (self.template / log["retained_path"]).write_text("43\n")
        with self.assertRaisesRegex(ValueError, "execution evidence"):
            release.verify_evidence(record, self.template)

    def test_failed_and_interrupted_results_do_not_pass(self):
        manifest, record, _ = self.nonapt()
        for mutation in ({"status": "failed"}, {"timed_out": True}, {"interrupted": True}, {"returncode": 1}):
            with self.subTest(mutation=mutation):
                candidate = copy.deepcopy(record)
                candidate["qualification"]["checks"]["results"][0].update(mutation)
                self.assertTrue(importer.installation_errors(candidate, manifest["package"]))

    def test_functional_evidence_bound_to_exact_archive(self):
        manifest, record, _ = self.nonapt()
        record["qualification"]["package_artifact"]["sha256"] = "0" * 64
        self.assertTrue(any("different or unidentified archive" in s for s in importer.installation_errors(record, manifest["package"])))

    def test_every_software_check_must_be_observed_exactly_once(self):
        manifest, record, _ = self.nonapt()
        record["qualification"]["checks"]["results"] *= 2
        self.assertTrue(any("exactly once" in s for s in importer.installation_errors(record, manifest["package"])))

    def test_publication_receipt_binds_uploaded_manifest_and_checksums(self):
        value = self.published()
        release.check_publication_receipt(value, "apt-001")
        value["packages"][0]["qualification"]["functional"] = "passed"
        with self.assertRaisesRegex(ValueError, "verified Release manifest"):
            release.check_publication_receipt(value, "apt-001")

    def test_release_asset_sets_hashes_sizes_states_are_exact(self):
        expected = {"a": {"sha256": "a" * 64, "bytes": 10}}
        valid = {"a": {"digest": "sha256:" + "a" * 64, "size": 10, "state": "uploaded"}}
        release.verify_assets(valid, expected, complete=True)
        release.verify_assets({}, expected, complete=False)
        for invalid in ({}, {"extra": valid["a"]}, {"a": {**valid["a"], "size": 11}},
                        {"a": {**valid["a"], "digest": None}}, {"a": {**valid["a"], "state": "starter"}}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                release.verify_assets(invalid, expected, complete=True)

    def test_duplicate_and_conflicting_release_identities_are_rejected(self):
        first = self.published()
        rows, summaries = release.published_rows([("apt-001", first)])
        self.assertEqual(len(rows), 1)
        second = copy.deepcopy(first)
        second["packages"].append(second["packages"][0])
        with self.assertRaises(ValueError):
            release.published_rows([("apt-001", first), ("apt-001", second)])

    def test_manifest_merge_preserves_each_verified_release(self):
        first = self.published()
        importer.write_json(self.root / "catalog/releases/apt-001.json", first)
        value = release.merge_manifest()
        self.assertEqual(value["packages"], first["packages"])
        self.assertEqual(value["releases"], [first["release"]])
        self.assertEqual(release.merge_manifest(), value)

    def test_plan_rejects_duplicate_checksums_and_wrong_repository(self):
        plan = self.plan()
        for candidate in ({**plan, "artifacts": plan["artifacts"] * 2}, {**plan, "repository": "other/repo"}):
            importer.write_json(self.root / "release-plans/apt-001.json", candidate)
            with self.assertRaises(ValueError):
                release.load_plan("apt-001")

    def test_source_cache_verifies_hash_and_size_without_network(self):
        cache = self.work / "cache"
        cache.mkdir()
        source = {"sha256": hashlib.sha256(b"original").hexdigest(), "bytes": 8, "url": "https://example.invalid/source"}
        cached = cache / source["sha256"]
        with self.assertRaises(FileNotFoundError):
            release.source_file(source, cache, network=False)
        cached.write_bytes(b"original")
        self.assertEqual(release.source_file(source, cache, network=False), cached)
        cached.write_bytes(b"modified")
        with self.assertRaises(ValueError):
            release.source_file(source, cache, network=False)

    def test_unsafe_components_cannot_collide_in_release_names(self):
        original = self.manifest["package"]
        names = [importer.artifact_name({**original, "version": v}, "wrapper", self.record["sha256"])
                 for v in ("1:2", "1/2", "1-2", "x" * 400, "x" * 399 + "y")]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(all("/" not in n and len(n) < 255 for n in names))

    def test_unsafe_archive_paths_are_rejected(self):
        for value in ("../escape", "/absolute", "a/../b", "a\\b", "a//b", "./a", "a\x00b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                importer.safe_relative(value)

    def prepare_validation_root(self):
        spec = copy.deepcopy(self.manifest["package"])
        importer.write_json(self.root / "packages" / spec["id"] / "package.json", spec)
        dependency = copy.deepcopy(spec)
        dependency.update(id="apt.libc6", dependencies={"build": [], "run": [], "system": []})
        importer.write_json(self.root / "packages/apt.libc6/package.json", dependency)
        importer.write_json(self.root / "packages/registry.json", {"resource_order": [spec["id"], "apt.libc6"]})
        release.merge_manifest()

    def test_repository_validator_enforces_full_qualification_gate(self):
        self.prepare_validation_root()
        self.assertEqual(validator.validate(self.root)["status"], "passed")
        record = {**self.record, "functional": "passed"}
        importer.write_json(self.root / "catalog/artifacts" / (record["sha256"] + ".json"), record)
        result = validator.validate(self.root)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(any("observed passing functional" in message for message in result["errors"]))

    def test_root_manifest_cannot_omit_a_verified_publication(self):
        self.prepare_validation_root()
        importer.write_json(self.root / "catalog/releases/apt-001.json", self.published())
        value = release.merge_manifest()
        self.assertEqual(validator.validate(self.root)["status"], "passed")
        value["packages"] = []
        importer.write_json(self.root / "manifest.json", value)
        result = validator.validate(self.root)
        self.assertEqual(result["status"], "failed")
        self.assertIn("Root manifest does not exactly preserve every verified publication", result["errors"])

    def test_foreign_catalogs_are_not_reinterpreted(self):
        self.prepare_validation_root()
        for relative in ("catalog/references/foreign-format.json", "resource-integrations/references/foreign-format.json"):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("unrelated schema; intentionally not parsed")
        self.assertEqual(validator.validate(self.root)["status"], "passed")

    def test_failed_download_does_not_remove_another_partial(self):
        class Response(io.BytesIO):
            def geturl(self):
                return "https://example.invalid/source"
        cache = self.work / "cache"
        cache.mkdir()
        source = {"sha256": hashlib.sha256(b"original").hexdigest(), "bytes": 8,
                  "url": "https://example.invalid/source"}
        other = cache / (source["sha256"] + ".part")
        other.write_bytes(b"another attempt")
        with patch.object(release, "urlopen", return_value=Response(b"too many bytes")):
            with self.assertRaisesRegex(ValueError, "locked byte size"):
                release.source_file(source, cache, network=True)
        self.assertEqual(other.read_bytes(), b"another attempt")
        self.assertEqual(list(cache.iterdir()), [other])

    def test_declared_cpg_unknown_schema_is_explicit_failure(self):
        unknown = self.work / "otelcol.online.cpgrecipe.tar.gz"
        descriptor = json.dumps({"format": "compiler-playground-original-material-online-recipe-v1",
                                 "resource_id": "otelcol", "original_version": "0.163.0",
                                 "original_sources": [], "files": []}).encode()
        with tarfile.open(unknown, "w:gz") as archive:
            member = tarfile.TarInfo("manifest.json")
            member.size = len(descriptor)
            archive.addfile(member, io.BytesIO(descriptor))
        for nested in (False, True):
            target = unknown
            if nested:
                target = self.work / "legacy.zip"
                with zipfile.ZipFile(target, "w") as archive:
                    archive.write(unknown, unknown.name)
                    archive.writestr("broken.cpgpkg.tar.gz", "not an archive")
            result = importer.inspect_archive(target, self.root, self.work / "rolling")
            self.assertEqual(result["status"], "inspected_with_failures")
            self.assertEqual(len(result["errors"]), 2 if nested else 1)
            self.assertTrue(all("declared CPG" in row["error"] for row in result["errors"]))
            self.assertEqual(result["nonpackage_members"], 0)
            self.assertEqual(list((self.work / "rolling").iterdir()), [])

    def test_invalid_tar_is_a_recorded_failure(self):
        broken = self.work / "broken.tar.gz"
        broken.write_bytes(b"\x1f\x8btruncated")
        result = importer.inspect_archive(broken, self.root, self.work / "rolling")
        self.assertEqual(result["status"], "inspected_with_failures")
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("Invalid outer TAR", result["errors"][0]["error"])

    def container(self, suffix, nested=False):
        package = release.rebuild(self.record, self.work / "input", self.work / "cache")
        target = self.work / ("delivery" + suffix)
        if suffix == ".zip":
            with zipfile.ZipFile(target, "w") as archive:
                archive.write(package, "objects/" + self.record["sha256"])
                archive.writestr("excluded-input.zip", package.read_bytes())
                archive.writestr("readme.txt", "ordinary text")
        else:
            with tarfile.open(target, "w:gz") as archive:
                archive.add(package, arcname="./objects/" + self.record["sha256"])
        return target

    def test_zip_and_tar_containers_stream_inner_package(self):
        for suffix in (".zip", ".tar.gz"):
            with self.subTest(suffix=suffix):
                archive = self.container(suffix)
                seen = []
                def inspect(path, root, origin, **kwargs):
                    seen.append((importer.sha256(path), origin["member"]))
                    return {"sha256": importer.sha256(path)}
                with patch.object(importer, "import_package", side_effect=inspect):
                    result = importer.inspect_archive(archive, self.root, self.work / "rolling", exclude=("excluded-input.zip",))
                self.assertEqual(len(result["packages"]), 1)
                self.assertEqual(seen[0][0], self.record["sha256"])
                self.assertEqual(list((self.work / "rolling").iterdir()), [])
                if suffix == ".zip":
                    self.assertEqual(result["excluded_members"], 1)

    @unittest.skipUnless(shutil.which("zstd"), "zstd not installed on this runner")
    def test_zstd_outer_tar_is_read_without_an_expanded_tree(self):
        original = self.container(".tar.gz")
        plain = self.work / "outer.tar"
        plain.write_bytes(gzip.decompress(original.read_bytes()))
        compressed = self.work / "outer.tar.zst"
        subprocess.run(["zstd", "-q", str(plain), "-o", str(compressed)], check=True)
        with patch.object(importer, "import_package", return_value={"sha256": self.record["sha256"]}):
            result = importer.inspect_archive(compressed, self.root, self.work / "rolling")
        self.assertEqual(len(result["packages"]), 1)
        self.assertEqual(list((self.work / "rolling").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
