#!/usr/bin/env python3
"""Host functional smoke of unmodified pinned Quicksilver (not a physics oracle)."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import tempfile

REV='eb68bb8d6fc53de1f65011d4e79ff2ed0dd60f3b'
EXPECT={
 'allAbsorb':{'path':'AllAbsorb/allAbsorb.inp','sha256':'b767bf69c3b4ed36d4fae1b65126ae0f066e2315d95ec69bdc4f1a69f3e86e1d','boundary':'reflect'},
 'allEscape':{'path':'AllEscape/allEscape.inp','sha256':'1219da6fc34fda1a701e54247d60b5c35ee3fd62092687ffd5b6ba9534125414','boundary':'escape'},
}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--prefix',type=Path,required=True)
    args=ap.parse_args();root=args.prefix
    binary=root/'bin/qs'
    assert binary.is_file()
    outputs=[]
    for name,spec in EXPECT.items():
        deck=root/'share/quicksilver/Examples'/spec['path']
        assert deck.is_file() and hashlib.sha256(deck.read_bytes()).hexdigest()==spec['sha256']
        with tempfile.TemporaryDirectory(prefix='cpg-quicksilver-') as temp:
            command=[str(binary),'-i',str(deck)]
            run=subprocess.run(command,cwd=temp,capture_output=True,text=True,timeout=60,check=False)
        stdout=run.stdout
        cycle_rows=re.findall(r'^\s*(\d+)\s+(\d+)\s+',stdout,flags=re.MULTILINE)
        cycle_ids=[int(i) for i,_ in cycle_rows if int(i)<=19]
        # Each original deck declares nSteps=20 and nParticles=9999.
        passed=(run.returncode==0 and not run.stderr.strip()
            and 'Quicksilver Git Hash    : '+REV in stdout
            and 'Number of MPI ranks     : 1' in stdout
            and 'Number of OpenMP Threads: 1' in stdout
            and 'Finished Consistency Check' in stdout
            and 'nParticles: 9999' in stdout and 'nSteps: 20' in stdout
            and 'boundaryCondition: '+spec['boundary'] in stdout
            and 'Figure Of Merit' in stdout
            and all(i in cycle_ids for i in range(20))
            and 'FATAL' not in stdout.upper() and 'ERROR' not in stdout.upper())
        outputs.append({'name':name,'returncode':run.returncode,'20_steps':all(i in cycle_ids for i in range(20)),
                        'stdout_sha256':hashlib.sha256(stdout.encode()).hexdigest(),
                        'stderr_tail':run.stderr[-500:],'functional_pass':passed})
    if not all(row['functional_pass'] for row in outputs):
        raise RuntimeError(json.dumps({'status':'failed','cases':outputs}))
    print(json.dumps({'status':'passed','cases':outputs,'test_scope':'CPU serial; original full input decks; functional smoke only; no physical result oracle or official benchmark grant'}))

if __name__=='__main__':main()
