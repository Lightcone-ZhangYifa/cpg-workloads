#!/usr/bin/env python3
"""Check freshly linked OpenSSL consumers and the exact installed ELF CLI."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',type=Path,required=True)
    parser.add_argument('--build',type=Path)
    parser.add_argument('--case',choices=('api','cli'),required=True)
    args=parser.parse_args();prefix=args.prefix.resolve(strict=True)
    config=json.loads(Path(__file__).with_name('config.json').read_text())
    environment=dict(os.environ,LC_ALL='C',PATH='/usr/bin:/bin')
    for name in list(environment):
        if name.startswith(('CPG_PERL','PERL','OPENSSL_')) or name in (
                'LD_LIBRARY_PATH','LD_PRELOAD','LIBRARY_PATH','CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH'):
            environment.pop(name,None)
    environment.update(OPENSSL_CONF='/dev/null',OPENSSL_MODULES=str(prefix/'lib/ossl-modules'))
    report={'resource':'openssl','status':'running','case':args.case,'prefix':str(prefix),'commands':[]}

    def run(argv,*,text_input=None,expected=0,without_perl=False):
        command=[str(x) for x in argv];env=dict(environment)
        if without_perl:env['PATH']=str(temporary/'empty-path')
        result=subprocess.run(command,env=env,input=text_input,capture_output=True,text=True,timeout=180)
        report['commands'].append({'argv':command,'input':text_input,'returncode':result.returncode,
            'stdout':result.stdout,'stderr':result.stderr,'PATH':env['PATH'],'perl_environment_removed':True})
        if (expected is None and result.returncode==0) or (expected is not None and result.returncode!=expected):
            raise RuntimeError('Unexpected status: '+command[0])
        return result

    try:
        profile=json.loads((prefix/'share/compiler-playground/openssl/profile.json').read_text())
        if profile['id']!='openssl' or profile['version']!='4.0.3' or profile['upstream_tests']['selected_recipes']!=config['upstream_recipes']:
            raise RuntimeError('Installed qualification profile differs from its recipe')
        if (prefix/'bin/openssl').read_bytes()[:4]!=b'\x7fELF':
            raise RuntimeError('The installed OpenSSL CLI is not the expected source-built ELF executable')
        with tempfile.TemporaryDirectory(prefix='cpg-openssl-functional-') as td:
            temporary=Path(td);(temporary/'empty-path').mkdir()
            version=run([prefix/'bin/openssl','version'],without_perl=True).stdout
            if not version.startswith('OpenSSL 4.0.3 '):raise RuntimeError('Wrong OpenSSL CLI version')
            if args.case=='api':
                report['consumers']=[]
                for kind in ('shared','static'):
                    executable=temporary/('consumer-'+kind)
                    libraries=[prefix/'lib'/('lib'+name+('.so' if kind=='shared' else '.a')) for name in ('ssl','crypto')]
                    run(['/usr/bin/gcc','-std=c11','-O2','-I'+str(prefix/'include'),Path(__file__).with_name('consumer.c'),
                        *libraries,'-Wl,-rpath,'+str(prefix/'lib'),'-pthread','-ldl','-o',executable])
                    result=json.loads(run([executable],without_perl=True).stdout)
                    if result!={'checks':10,'invalid_inputs_rejected':3,'version':'4.0.3','status':'passed'}:
                        raise RuntimeError('Fresh OpenSSL C consumer returned incomplete results')
                    links=run(['/usr/bin/ldd',executable]).stdout
                    if 'not found' in links:raise RuntimeError('Consumer dynamic dependency is missing')
                    for name in ('ssl','crypto'):
                        found=[line for line in links.splitlines() if 'lib'+name+'.so' in line]
                        if kind=='shared' and (len(found)!=1 or str(prefix/'lib')+'/' not in found[0]):
                            raise RuntimeError('Consumer resolved a different '+name+' prefix')
                        if kind=='static' and found:raise RuntimeError('Static consumer linked a shared OpenSSL library')
                    report['consumers'].append({'link':kind,'result':result,'runtime_PATH_empty':True})
            else:
                executable=prefix/'bin/openssl';cases=[]
                digest=run([executable,'dgst','-sha256','-r'],text_input='abc',without_perl=True).stdout.split()[0]
                if digest!='ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad':raise RuntimeError('CLI SHA-256 oracle')
                cases.append('sha256-known-answer')
                hmac=run([executable,'dgst','-sha256','-hmac','key','-r'],
                    text_input='The quick brown fox jumps over the lazy dog',without_perl=True).stdout.split()[0]
                if hmac!='f7bc83f430538424b13298e6aa6fb143ef4d59a14946175997479dbc2d1a3cd8':raise RuntimeError('CLI HMAC oracle')
                cases.append('hmac-known-answer')
                plain,cipher,decoded=temporary/'plain',temporary/'cipher',temporary/'decoded';plain.write_bytes(bytes(16))
                options=['-aes-128-ecb','-K','0'*32,'-nosalt','-nopad']
                run([executable,'enc',*options,'-in',plain,'-out',cipher],without_perl=True)
                if cipher.read_bytes().hex()!='66e94bd4ef8a2c3b884cfa59ca342b2e':raise RuntimeError('CLI AES known answer')
                cases.append('aes-ecb-known-answer')
                run([executable,'enc','-d',*options,'-in',cipher,'-out',decoded],without_perl=True)
                if decoded.read_bytes()!=plain.read_bytes():raise RuntimeError('CLI AES round trip')
                cases.append('aes-ecb-round-trip')
                if run([executable,'base64','-A'],text_input='abc',without_perl=True).stdout!='YWJj':raise RuntimeError('CLI base64 encode')
                cases.append('base64-encode')
                if run([executable,'base64','-d','-A'],text_input='YWJj',without_perl=True).stdout!='abc':raise RuntimeError('CLI base64 decode')
                cases.append('base64-decode')
                providers=run([executable,'list','-providers','-verbose','-provider','default','-provider','legacy'],without_perl=True).stdout
                if providers.count('version: 4.0.3')!=2 or providers.count('status: active')!=2:
                    raise RuntimeError('Selected default/legacy providers not loaded from this installation')
                cases.append('default-and-legacy-providers')
                malformed=temporary/'bad.pem';malformed.write_text('not a PEM private key\n')
                report['negative_controls']=[]
                for name,argv in [('invalid-pem',['pkey','-in',malformed]),
                    ('unknown-cipher',['enc','-CPG_NONEXISTENT_CIPHER','-in',plain]),
                    ('unknown-digest',['dgst','-CPG_NONEXISTENT_DIGEST','-r'])]:
                    rejected=run([executable,*argv],expected=None,without_perl=True)
                    if not rejected.stderr.strip():raise RuntimeError('Invalid input failed without a diagnostic')
                    report['negative_controls'].append({'name':name,'status':'rejected'})
                report['cli_cases']=cases
            report['runtime_without_perl']={'status':'passed','method':'Exact ELF executables run with an empty PATH and no Perl environment','optional_c_rehash_script':'not_qualified'}
        report['status']='passed'
    except BaseException as error:
        report.update(status='failed',error=f'{type(error).__name__}: {error}');raise
    finally:
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
