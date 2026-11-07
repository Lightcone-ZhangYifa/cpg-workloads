#!/usr/bin/env python3
import argparse,json,subprocess,sys,xml.etree.ElementTree as ET
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    p=Path(a.prefix).resolve();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
    (out/'result.json').unlink(missing_ok=True)
    cfg=json.loads((p/'profile.json').read_text());index=json.loads((p/'index.json').read_text());rid=cfg['id'];checks=[]
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise RuntimeError(name+' failed')
    if rid=='research.ecma335':
        tree=ET.parse(p/'upstream/CLILibraryTypes.xml').getroot()
        actual={(g.attrib['Library'],t.attrib['FullName']) for g in tree.findall('Types') for t in g.findall('Type')}
        indexed={(x['library'],x['name']) for x in index if x['kind']=='cli_type'}
        check('CLI_XML_type_index_complete',actual==indexed and len(indexed)==374)
        text=(p/'materials/ECMA-335-6th-layout.txt').read_text();check('PDF_extraction_bound_to_edition',text.count('\f')==574 and '6th Edition / June 2012' in text)
        opcodes=[x for x in index if x['kind']=='opcode_encoding_reference'];tables=[x for x in index if x['kind']=='metadata_table']
        check('OPDEF_rows_backed_by_official_text',len(opcodes)==cfg['opcode_rows'] and all(x['symbol'] in text and '"'+x['mnemonic']+'"' in text for x in opcodes))
        normative=[x for x in index if x['kind']=='opcode']
        check('normative_instruction_families',len(normative)==106 and {'constrained.','readonly.','no.','unbox.any','ldelem','stelem'}<={x['mnemonic'] for x in normative})
        check('metadata_table_index',len(tables)==cfg['metadata_tables'] and {'TypeDef','MethodDef','AssemblyRef'}<={x['name'] for x in tables})
        check('copyright_notice_retained','COPYRIGHT NOTICE' in (p/'materials/COPYRIGHT-NOTICE.txt').read_text())
        query,kind='System.Object','cli_type'
    else:
        check('fixed_Java_SE17',cfg['java_edition']==17 and cfg['classfile_major_for_edition']==61)
        families=[x for x in index if x['kind']=='instruction_family'];check('instruction_family_index',len(families)==149 and len({x['symbol'] for x in families})==149)
        check('classfile_and_verification_coverage',{'4.1','4.7.4','4.10','4.10.1.9'}<={x.get('section') for x in index})
        check('only_fixed_official_edition_links',all(x['url'].startswith('https://docs.oracle.com/javase/specs/') and '/se17/' in x['url'] for x in index))
        check('license_boundary_recorded','不含Oracle规范正文' in (p/'LICENSE-SCOPE.zh.txt').read_text())
        query,kind='iadd','instruction_family'
    r=subprocess.run([sys.executable,'-B',str(p/'lookup.py'),'--query',query,'--kind',kind],capture_output=True,text=True,timeout=60)
    (out/'lookup.json').write_text(r.stdout);check('offline_index_query',r.returncode==0 and len(json.loads(r.stdout))>0)
    bad=subprocess.run([sys.executable,'-B',str(p/'lookup.py'),'--query','CPG_NONEXISTENT_SYMBOL_5297'],capture_output=True,text=True,timeout=60)
    (out/'missing-query.json').write_text(bad.stdout);check('missing_symbol_rejected',bad.returncode==2 and json.loads(bad.stdout)==[])
    result={'schema_version':1,'resource_id':rid,'status':'passed','qualification':'material_only','checks':checks,'index_rows':len(index),'evidence_files':['lookup.json','missing-query.json'],'scope':cfg['scope']}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));print('CPG_CHECK_PASS '+rid)

if __name__=='__main__':main()
