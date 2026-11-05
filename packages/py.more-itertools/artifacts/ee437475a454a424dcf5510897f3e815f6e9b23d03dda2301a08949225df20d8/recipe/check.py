#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(mi, work):
    """Check iterator recipes, stateful seeking and finite error cases."""
    require(list(mi.chunked(range(7),3)) == [[0,1,2],[3,4,5],[6]], 'Chunk boundaries wrong')
    require(list(mi.windowed([1,2,3,4],3)) == [(1,2,3),(2,3,4)], 'Sliding windows wrong')
    false,true = mi.partition(lambda value:value%2 == 0,range(6))
    require(list(false) == [1,3,5] and list(true) == [0,2,4], 'Iterator partition wrong')
    require(list(mi.unique_everseen([[1],[2],[1]],key=tuple)) == [[1],[2]], 'Stable uniqueness wrong')
    head,tail = mi.spy(iter([1,2,3]),2)
    require(head == [1,2] and list(tail) == [1,2,3], 'Spy consumed the original prefix')
    values = mi.seekable([10,20,30]); require(next(values) == 10 and next(values) == 20, 'Seekable initial values wrong')
    values.seek(0); require(list(values) == [10,20,30], 'Seekable replay failed')
    raises(ValueError, lambda: list(mi.chunked(range(5),3,strict=True)), 'Strict uneven chunks accepted')
    columns = mi.unzip([(1,'a'),(2,'b')])
    require([list(column) for column in columns] == [[1,2],['a','b']], 'Unzip transpose failed')
    raises(ValueError, lambda: mi.one([1,2]), 'Multiple values accepted by one')
    raises(ValueError, lambda: mi.one([]), 'Empty singleton accepted')
    return {'checks':['chunked','windowed','partition','stable-uniqueness','spy-prefix','seekable-replay','strict-chunk-error','unzip-transpose','multiple-singleton','empty-singleton']}

if __name__ == "__main__":
    raise SystemExit(main('more-itertools', 'more_itertools', functional))
