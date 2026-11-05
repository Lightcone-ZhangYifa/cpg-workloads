#!/usr/bin/env python3
import argparse,importlib,importlib.metadata as meta,json,os,pathlib,sys
ap=argparse.ArgumentParser();ap.add_argument('--prefix',required=True);ap.add_argument('--module',required=True);ap.add_argument('--dist',required=True);ap.add_argument('--version',required=True);a=ap.parse_args()
prefix=pathlib.Path(a.prefix).resolve(); assert pathlib.Path(sys.prefix).resolve()==prefix,(sys.prefix,prefix)
assert meta.version(a.dist)==a.version,(meta.version(a.dist),a.version)
m=importlib.import_module(a.module); origin=pathlib.Path(m.__file__).resolve()
assert origin.is_relative_to(prefix),(origin,prefix)
if a.module=='six':
 import six; assert list(six.iteritems({'answer':42}))==[('answer',42)]
elif a.module=='pycparser':
 from pycparser import c_parser,c_ast
 ast=c_parser.CParser().parse('int main(void) { return 7; }');assert isinstance(ast,c_ast.FileAST) and ast.ext[0].decl.name=='main'
else:raise AssertionError('unapproved qualification module')
print(json.dumps({'status':'passed','module':a.module,'version':a.version,'isolated_prefix':str(prefix),'origin':str(origin),'functional_smoke':True},sort_keys=True))
