import smmap,pathlib,tempfile
with tempfile.TemporaryDirectory(prefix='cpg-smmap-') as temp:
    path=pathlib.Path(temp)/'test.bin'
    path.write_bytes(b'abcdef' * 128)
    manager=smmap.SlidingWindowMapManager(window_size=4096)
    cursor=manager.make_cursor(str(path))
    cursor.use_region(0,12)
    assert cursor.is_valid() and bytes(cursor.buffer()[:6])==b'abcdef'
    cursor.unuse_region()
    assert not cursor.is_valid()
print('CPG_FUNCTIONAL_OK:smmap:actual-mmap-cursor')
