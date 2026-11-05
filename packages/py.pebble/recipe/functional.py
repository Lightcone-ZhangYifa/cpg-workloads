from pebble import ThreadPool
with ThreadPool(max_workers=2) as pool:
    task=pool.schedule(pow,args=(6,2))
    assert task.result(timeout=10)==36
print('CPG_FUNCTIONAL_OK:pebble:bounded-thread-pool')
