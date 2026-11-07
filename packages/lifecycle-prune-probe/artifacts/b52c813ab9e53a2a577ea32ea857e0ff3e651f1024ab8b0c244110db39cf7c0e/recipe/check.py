#!/usr/bin/env python3
import json,pathlib,subprocess,sys
if not __debug__:raise RuntimeError('Optimization is forbidden')
p=pathlib.Path(sys.argv[1]).resolve()
binary=p/'bin/answer'
if not binary.is_file() or binary.is_symlink():raise RuntimeError('Missing ordinary binary')
if '--material-only' not in sys.argv:
    good=subprocess.run([str(binary)],capture_output=True,text=True)
    bad=subprocess.run([str(binary),'invalid'],capture_output=True,text=True)
    if (good.returncode,good.stdout)!=(0,'42\n'):raise RuntimeError('Positive execution failed')
    if bad.returncode!=2 or 'invalid argument' not in bad.stderr:raise RuntimeError('Negative execution failed')
print(json.dumps({'status':'passed','scope':'tiny independent native fixture'}))
