#!/usr/bin/env python3
"""Read a CPG static-material profile without running upstream tooling or networking."""
import argparse,json,pathlib,sys,tarfile

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parent)
    choice=parser.add_mutually_exclusive_group()
    choice.add_argument('--list',action='store_true',help='List curated topics and source archives')
    choice.add_argument('--search',help='Case-insensitive literal search over indexed UTF-8 references')
    choice.add_argument('--show',help='Read an exact original archive member named by the index')
    parser.add_argument('--archive',help='Archive path for --show, required if the member is ambiguous')
    parser.add_argument('--limit',type=int,default=20)
    args=parser.parse_args()
    if not 1<=args.limit<=200:parser.error('--limit must be between 1 and 200')
    root=args.root.resolve()
    index=json.loads((root/'material-index.json').read_text())
    if args.search is not None:
        if not args.search:parser.error('search term must not be empty')
        q=args.search.casefold();matches=[]
        for line in (root/'reference-text.jsonl').read_text().splitlines():
            record=json.loads(line)
            for lineno,text in enumerate(record['text'].splitlines(),1):
                if q in text.casefold():
                    matches.append({'archive':record['archive'],'member':record['member'],'line':lineno,'text':text[:300]})
                    if len(matches)>=args.limit:break
            if len(matches)>=args.limit:break
        # Reference-only commercial profiles are original authored notes, not copied manuals.
        if not matches:
            for lineno,text in enumerate((root/'MATERIALS.md').read_text().splitlines(),1):
                if q in text.casefold():matches.append({'member':'MATERIALS.md','line':lineno,'text':text[:300]})
                if len(matches)>=args.limit:break
        print(json.dumps({'logical_resource_id':index['logical_resource_id'],'matches':matches,'truncated_at':args.limit,'collection_performed':False},ensure_ascii=False,indent=2))
    elif args.show is not None:
        records=json.loads((root/'archive-members.json').read_text())
        matches=[r for r in records if r['member']==args.show and r['type']=='file' and (args.archive is None or r['archive']==args.archive)]
        if len(matches)!=1:parser.error('member must uniquely identify one declared regular archive file')
        rec=matches[0]; archive=root/rec['archive']
        if not archive.resolve().is_relative_to(root):parser.error('archive escapes installed prefix')
        if rec['bytes']>4*1024*1024:parser.error('use an archive reader for members larger than 4 MiB')
        with tarfile.open(archive) as t:
            member=t.getmember(rec['member'])
            if not member.isfile():parser.error('the selected member is not a regular file')
            data=t.extractfile(member).read()
        try:txt=data.decode('utf-8')
        except UnicodeDecodeError:parser.error('binary document; read the original member with a suitable viewer')
        sys.stdout.write(txt)
    else:print(json.dumps(index,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
