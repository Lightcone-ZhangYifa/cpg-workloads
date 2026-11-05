#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise concurrent request coalescing, eviction and exception behavior."""
    import asyncio
    async def exercise():
        calls = []
        @module.alru_cache(maxsize=2)
        async def square(value):
            calls.append(value)
            await asyncio.sleep(0)
            if value < 0:
                raise ValueError("negative")
            return value * value
        try:
            require(await asyncio.gather(square(3), square(3), square(3)) == [9, 9, 9], "Concurrent result mismatch")
            require(calls == [3], "Concurrent requests were not coalesced")
            require(await square(3) == 9 and square.cache_info().hits >= 3, "Cache hit failed")
            require(square.cache_invalidate(3), "Cache invalidation failed")
            require(await square(3) == 9 and calls == [3, 3], "Invalidation did not recompute")
            await square(4); await square(5)
            require(square.cache_info().currsize == 2, "Cache bound failed")
            before = calls.count(3)
            require(await square(3) == 9 and calls.count(3) == before + 1, "LRU eviction did not force recomputation")
            for unused in range(2):
                try:
                    await square(-1)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Exception was suppressed")
            require(calls.count(-1) == 2, "Failed result incorrectly cached")
        finally:
            await square.cache_close()
    asyncio.run(exercise())
    return {"checks": ["concurrent-coalescing", "cache-hit", "invalidation", "bounded-cache", "lru-eviction-recomputation", "exceptions-not-cached", "task-cleanup"]}

if __name__ == "__main__":
    raise SystemExit(main('async-lru', 'async_lru', functional))
