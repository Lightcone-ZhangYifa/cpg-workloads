"""Bounded source intake preserves exact source locks and never qualifies ZIP leads."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from authored_inputs import descriptor_for
from history_ledger import index_zip
from history_intake import candidate_jobs, check_template, worker_labeled_id
from history_manifest_ledger import hashes
from history_object_lineage import category


class HistoryIntakeTests(unittest.TestCase):
    def test_nested_archive_requires_original_exact_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            name = 'recipe/tool/materials/source.tar.gz'
            content = b'source bytes'
            digest = hashlib.sha256(content).hexdigest()
            row = {'path': name, 'kind': 'file', 'bytes': len(content), 'sha256': digest, 'mode': 0o644}
            spec = {'id': 'example', 'sources': [{'id': 'source', 'sha256': digest,
                'bytes': len(content), 'url': 'https://example.org/source.tar.gz'}]}
            manifest = {'manifest_sha256': '1' * 64, 'method': 'source', 'package': spec, 'files': [row]}
            record = {'sha256': '2' * 64, 'bytes': 100, 'manifest_sha256': '1' * 64,
                      'method': 'source', 'id': 'example'}
            descriptor = descriptor_for(record, manifest, root)
            self.assertEqual(descriptor['members'][name]['source']['url'], spec['sources'][0]['url'])
            spec['sources'][0]['sha256'] = '3' * 64
            with self.assertRaisesRegex(ValueError, 'no exact original HTTPS source lock'):
                descriptor_for(record, manifest, root)

    def test_zip_names_are_leads_with_no_crc_claim(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('foo.cpgpkg', b'not a package')
                z.writestr('../unsafe', b'bad')
            result = index_zip(path)
            self.assertEqual(result['cpg_name_leads'][0]['path'], 'foo.cpgpkg')
            self.assertEqual(result['unsafe_names'], ['../unsafe'])
            self.assertFalse(result['payload_crc_verified'])

    def test_unsafe_zip_lead_is_carried_as_a_blocker(self):
        ledger = {'files': [{'path': 'outer.zip', 'bytes': 10, 'sha256': 'a' * 64,
                             'zip_index_key': 'file:a'}], 'split_families': [],
                  'zip_indexes': {'file:a': {'duplicate_names': ['x'], 'unsafe_names': [],
                      'cpg_name_leads': [{'path': 'x.cpgpkg', 'bytes': 2}]}}}
        jobs = list(candidate_jobs(ledger, None, None))
        self.assertTrue(jobs[0]['unsafe_container'])

    def test_authored_payload_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'grammar.g4').write_text('grammar G;')
            self.assertEqual(check_template(root), 'authored_payload_requires_review')

    def test_unpacked_upstream_source_projection_is_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); material = root / 'recipe/materials/upstream/source.c'
            material.parent.mkdir(parents=True);material.write_text('int main(void) { return 0; }')
            self.assertEqual(check_template(root), 'authored_source_projection_requires_review')

    def test_worker_labeled_original_identity_stays_out_of_public_tree(self):
        self.assertTrue(worker_labeled_id('reference-pack.worker-010'))
        self.assertTrue(worker_labeled_id('cpg-worker031-runtime'))
        self.assertFalse(worker_labeled_id('tree-sitter'))

    def test_hash_named_members_are_leads_only_when_size_and_lock_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'x.zip'; digest = 'a' * 64
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('objects/' + digest, b'abc')
            result = index_zip(path, {digest: {'source_bytes': {3}}})
            self.assertEqual(result['known_object_leads'][0]['role'], 'raw_source')
            self.assertFalse(result['payload_crc_verified'])
            self.assertFalse(index_zip(path, {digest: {'source_bytes': {4}}})['known_object_leads'])

    def test_standalone_package_is_a_distinct_intake_job(self):
        ledger = {'files': [{'path': 'x.cpgpkg', 'bytes': 10, 'sha256': 'a' * 64}],
                  'split_families': [], 'zip_indexes': {}}
        jobs = list(candidate_jobs(ledger, None, None))
        self.assertEqual(jobs[0]['kind'], 'standalone')

    def test_manifest_declared_hashes_remain_distinct_from_verified_members(self):
        value = {'source_sha256': 'a' * 64, 'files': [{'sha256': 'b' * 64}],
                 'description': 'c' * 64}
        self.assertEqual(set(hashes(value)), {'a' * 64, 'b' * 64})

    def test_path_categories_keep_git_and_evidence_separate(self):
        self.assertEqual(category('compiler-playground/.git/objects/ab/cd', 'core'), 'git_state')
        self.assertEqual(category('workspace-evidence/datasets/run.json', 'core'), 'historical_evidence')
        self.assertEqual(category('compiler-playground/src/optimizer.py', 'core'), 'framework_source')


if __name__ == '__main__': unittest.main()
