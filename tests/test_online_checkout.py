"""Fresh shared Git checkout permissions do not change locked recipe bytes."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import online_recipe


class OnlineCheckoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.record = json.loads((ROOT / "catalog/artifacts/005a3e4748ea3de5f71d18879d3c2ac95b0f4b3e22cbe8134953141c832b612b.json").read_text())
        self.template = self.root / "template"
        shutil.copytree(ROOT / self.record["template"], self.template)
        for path in self.template.rglob("*"):
            if path.is_dir():
                path.chmod(0o775)
            else:
                path.chmod(0o775 if path.stat().st_mode & 0o111 else 0o664)

    def test_shared_checkout_verifies_and_repack_restores_original_modes(self):
        online_recipe.verify_template(self.template, self.record)
        archive = self.root / "recipe.tar.gz"
        online_recipe.repack(self.template, self.record, archive)
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), self.record["sha256"])
        with tarfile.open(archive) as stream:
            actual = {member.name: member.mode for member in stream}
        self.assertEqual(actual, {row["path"]: row["mode"] for row in self.record["archive_members"]})

    def test_shared_checkout_still_rejects_world_write_and_changed_bytes(self):
        target = self.template / "offline-manifest.json"
        target.chmod(0o666)
        with self.assertRaisesRegex(ValueError, "identity differs"):
            online_recipe.verify_template(self.template, self.record)
        target.chmod(0o664)
        target.write_bytes(target.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "identity differs"):
            online_recipe.verify_template(self.template, self.record)
