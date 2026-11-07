"""Grammar extension for the existing py.lark identity."""
import argparse
import json
from pathlib import Path
from lark import Lark, Transformer, UnexpectedInput
import lark

class Ast(Transformer):
    def number(self, items): return ("num", int(items[0]))
    def variable(self, items): return ("var", str(items[0]))
    def add(self, items): return ("add", *items)
    def sub(self, items): return ("sub", *items)
    def mul(self, items): return ("mul", *items)
    def pow(self, items): return ("pow", *items)

def verify(grammar_file):
    assert lark.__version__ == "1.3.1", lark.__version__
    grammar=grammar_file.read_text()
    parsers={kind:Lark(grammar, parser=kind, propagate_positions=True) for kind in ("lalr","earley")}
    cases=[]
    positives=[
        ("precedence","2 + 3 * 4",("add",("num",2),("mul",("num",3),("num",4)))),
        ("parentheses","(2 + 3) * 4",("mul",("add",("num",2),("num",3)),("num",4))),
        ("left_associative","9 - 3 - 1",("sub",("sub",("num",9),("num",3)),("num",1))),
        ("right_associative","2 ** 3 ** 2",("pow",("num",2),("pow",("num",3),("num",2)))),
        ("unicode","变量 + 2",("add",("var","变量"),("num",2))),
    ]
    for kind,parser in parsers.items():
        for name,text,expected in positives:
            tree=parser.parse(text)
            actual=Ast().transform(tree)
            assert actual==expected, (kind,name,actual)
            cases.append({"case":name,"parser":kind,"input":text,"ast":actual,"passed":True})
        for name,text,line,column in [("missing_operand","2 + * 3",1,5),
                                     ("multiline_error","2 +\n * 3",2,2),
                                     ("trailing_input","2 3",1,3)]:
            try:parser.parse(text)
            except UnexpectedInput as exc:
                assert (exc.line,exc.column)==(line,column), (kind,name,exc.line,exc.column)
                cases.append({"case":name,"parser":kind,"line":exc.line,"column":exc.column,"passed":True})
            else:raise AssertionError("Invalid input accepted")
    tree=parsers["lalr"].parse("变量 + 2")
    token=next(tree.scan_values(lambda x: getattr(x,"type",None)=="NAME"))
    assert (token.start_pos, token.end_pos, token.line, token.column)==(0,2,1,1)
    cases.append({"case":"unicode_character_span","start":token.start_pos,"end":token.end_pos,
                  "coordinate_system":"Python character offsets, not UTF-8 byte offsets","passed":True})
    return {"resource_id":"py.lark","version":"1.3.1","status":"passed","test_count":len(cases),
            "new_tool_identity":False,"scope":"existing identity reused; grammar assets and LALR/Earley cross-check",
            "module_path":lark.__file__,"cases":cases}

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--grammar",type=Path,required=True)
    p.add_argument("--report",type=Path)
    a=p.parse_args();r=verify(a.grammar)
    if a.report: a.report.write_text(json.dumps(r,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(r,ensure_ascii=False))

