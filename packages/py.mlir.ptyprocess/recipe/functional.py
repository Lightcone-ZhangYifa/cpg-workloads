from ptyprocess import PtyProcess
import sys
p=PtyProcess.spawn([sys.executable,'-c','print("MLIR_PTY_42",flush=True)'])
text=p.read(4096)
p.wait()
assert b'MLIR_PTY_42' in text and p.exitstatus==0
print('CPG_FUNCTIONAL_OK:ptyprocess:mlir-role-popen')
