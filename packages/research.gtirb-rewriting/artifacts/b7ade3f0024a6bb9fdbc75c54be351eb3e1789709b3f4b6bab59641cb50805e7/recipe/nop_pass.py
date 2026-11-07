import sys
import json
from pathlib import Path
import gtirb
from gtirb_rewriting import (
    AllFunctionsScope, BlockPosition, FunctionPosition,
    Pass, PassManager, Patch, patch_constraints,
)

class NopPass(Pass):
    def __init__(self):
        self.insertions = 0

    def begin_module(self, module, functions, context):
        context.register_insert(
            AllFunctionsScope(FunctionPosition.ENTRY, BlockPosition.ENTRY),
            Patch.from_function(self.patch),
        )

    @patch_constraints()
    def patch(self, context):
        self.insertions += 1
        return "nop"

if __name__ == '__main__':
    ir = gtirb.IR.load_protobuf(sys.argv[1])
    before = sum(len(bi.contents) for mod in ir.modules for sec in mod.sections for bi in sec.byte_intervals)
    patch = NopPass()
    manager = PassManager()
    manager.add(patch)
    manager.run(ir)
    after = sum(len(bi.contents) for mod in ir.modules for sec in mod.sections for bi in sec.byte_intervals)
    if patch.insertions < 2 or after <= before:
        raise RuntimeError('Expected real inserted code in multiple function entries')
    ir.save_protobuf(sys.argv[2])
    result = {'insertions': patch.insertions, 'bytes_before': before, 'bytes_after': after,
              'patch': 'nop', 'clobbers': [], 'status': 'passed'}
    Path(sys.argv[3]).write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
