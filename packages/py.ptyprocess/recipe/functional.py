from ptyprocess import PtyProcess
import sys
p=PtyProcess.spawn([sys.executable,'-c','print("CPG_PTY_42",flush=True)'])
out=p.read(4096)
p.wait()
assert b'CPG_PTY_42' in out and p.exitstatus==0,(out,p.exitstatus)
print('CPG_FUNCTIONAL_OK:ptyprocess:pseudo-terminal-process')
