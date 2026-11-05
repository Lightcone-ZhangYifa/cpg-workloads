import fsspec,uuid
fs=fsspec.filesystem('memory')
key='/cpg-functional-'+uuid.uuid4().hex
with fs.open(key,'wb') as f:f.write(b'answer=42')
assert fs.cat(key)==b'answer=42'
fs.rm(key)
assert not fs.exists(key)
print('CPG_FUNCTIONAL_OK:fsspec:memory-file-lifecycle')
