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
from history_intake import candidate_jobs, check_template


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


if __name__ == '__main__': unittest.main()
