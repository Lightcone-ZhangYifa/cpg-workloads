#!/usr/bin/env python3
"""Installed sortedcontainers check for ordered mutations, ranges and set algebra."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import main, raises, require

def functional(sc, work):
    """Exercise the list/dict/set interfaces against exact ordered answers."""
    values = sc.SortedList([5, 1, 3, 3]); values.add(2); values.update([0, 7])
    require(list(values) == [0, 1, 2, 3, 3, 5, 7], "SortedList order/duplicates wrong")
    require(values.bisect_left(3) == 3 and values.bisect_right(3) == 5, "Bisect duplicate bounds wrong")
    require(list(values.irange(2, 5)) == [2, 3, 3, 5] and values[1:4] == [1, 2, 3], "Range/slice wrong")
    values.remove(3); values.discard(99)
    require(values.count(3) == 1, "Remove/discard changed the wrong values")
    keyed = sc.SortedKeyList([("a", 3), ("b", 1), ("c", 2)], key=lambda item: item[1])
    require([x[0] for x in keyed] == ["b", "c", "a"], "Key ordering wrong")
    mapping = sc.SortedDict({3: "c", 1: "a", 2: "b"})
    require(mapping.peekitem(0) == (1, "a") and list(mapping) == [1, 2, 3], "SortedDict ordering wrong")
    require(mapping.popitem(-1) == (3, "c") and list(mapping.irange(1, 2)) == [1, 2], "SortedDict mutation/range wrong")
    left = sc.SortedSet([1, 3, 2, 2]); right = sc.SortedSet([2, 4])
    require(list(left | right) == [1, 2, 3, 4] and list(left & right) == [2] and list(left - right) == [1, 3], "Set algebra wrong")
    raises(ValueError, lambda: values.remove(100), "Removal of missing value accepted")
    raises(IndexError, lambda: values[100], "Invalid list index accepted")
    raises(TypeError, lambda: sc.SortedList([1, "a"]), "Incomparable values accepted")
    return {"checks": ["list-order-and-duplicates", "bisect-bounds", "ranges-and-slices", "list-mutation",
                       "key-order", "sorted-dict", "set-algebra", "missing-value", "invalid-index", "incomparable-types"]}

if __name__ == "__main__":
    raise SystemExit(main("sortedcontainers", "sortedcontainers", functional))
