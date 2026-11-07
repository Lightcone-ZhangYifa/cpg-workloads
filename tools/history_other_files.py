#!/usr/bin/env python3
"""Identify non-ZIP historical inputs by header and inspect compressed JSONL metadata."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import zipfile
from import_archives import safe_relative


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--disposition',type=Path,required=True)
    p.add_argument('--history-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    history=a.history_root.resolve();output=a.output.resolve()
    if output.is_relative_to(history) or output.exists():p.error('Output must be new and outside historical input')
    d=json.loads(a.disposition.read_text());rows=[]
    for row in d['files']:
        if row['disposition']!='unclassified_file_pending':continue
        path=history.joinpath(*safe_relative(row['path']).parts);entry={'path':row['path'],'sha256':row['sha256'],'bytes':row['bytes']}
        h=hashlib.sha256();n=0
        with path.open('rb') as f:
            header=f.read(16);h.update(header);n+=len(header)
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block);n+=len(block)
        if h.hexdigest()!=row['sha256'] or n!=row['bytes']:raise ValueError('File identity changed: '+row['path'])
        entry['magic_hex']=header.hex();entry['sha256_verified']=True;low=path.name.lower()
        if header.startswith(b'%PDF-'):entry['kind']='pdf_historical_document_or_evidence'
        elif header.startswith(b'\x89PNG\r\n\x1a\n'):entry['kind']='png_historical_evidence'
        elif low.endswith('.xlsx') and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:entry.update(kind='xlsx_historical_reference',zip_member_count=len(z.infolist()))
        elif header.startswith(b'# v2 git bundle') or header.startswith(b'# v3 git bundle'):
            entry['kind']='git_bundle_historical_delivery'
        elif low.endswith('.jsonl.gz') and header.startswith(b'\x1f\x8b'):
            count=0;invalid=0
            with gzip.open(path,'rt',encoding='utf-8') as f:
                for line in f:
                    count+=1
                    try:json.loads(line)
                    except ValueError:invalid+=1
            entry.update(kind='compressed_jsonl_historical_metadata',lines=count,invalid_json_lines=invalid,gzip_stream_read=True)
        elif low.endswith('.jsonl'):
            count=0;invalid=0
            with path.open(encoding='utf-8') as f:
                for line in f:
                    count+=1
                    try:json.loads(line)
                    except ValueError:invalid+=1
            entry.update(kind='jsonl_historical_metadata',lines=count,invalid_json_lines=invalid)
        elif low.endswith('.log'):entry['kind']='historical_log_evidence'
        elif low.endswith('.tar.gz') and header.startswith(b'\x1f\x8b'):entry['kind']='gzip_archive_stream_validation_separate'
        else:entry['kind']='unknown_pending'
        rows.append(entry)
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:json.dump({'schema_version':1,'inventory_sha256':d['inventory_sha256'],'files':rows},f,indent=2,ensure_ascii=False);f.write('\n')
    from collections import Counter
    print(json.dumps({'files':len(rows),'kinds':dict(Counter(x['kind'] for x in rows))}))

if __name__=='__main__':main()
