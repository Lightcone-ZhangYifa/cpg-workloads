from websocket import ABNF
fr=ABNF.create_frame('cpg',ABNF.OPCODE_TEXT)
assert fr.opcode==ABNF.OPCODE_TEXT
wire=fr.format()
assert (wire[0]&15)==ABNF.OPCODE_TEXT and len(wire)>=7
print('CPG_FUNCTIONAL_OK:websocket-client:wire-frame-encoding')
