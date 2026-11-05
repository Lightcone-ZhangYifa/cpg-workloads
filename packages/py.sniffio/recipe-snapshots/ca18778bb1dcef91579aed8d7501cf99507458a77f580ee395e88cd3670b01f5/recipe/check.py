#!/usr/bin/env python3
"""Bounded installed functional qualification; no external requests."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(module, work):
    'Detect an actual running asyncio loop and reject synchronous context.'
    import asyncio
    raises(module.AsyncLibraryNotFoundError, module.current_async_library, "Synchronous context reported an async library")
    async def inspect():
        await asyncio.sleep(0)
        return module.current_async_library()
    require(asyncio.run(inspect()) == "asyncio", "Running event loop was not identified")
    raises(module.AsyncLibraryNotFoundError, module.current_async_library, "Async context leaked after loop shutdown")
    return {"checks": ["sync-context-error", "actual-asyncio-detection", "context-restored-after-loop"]}

if __name__ == '__main__':
    raise SystemExit(main('sniffio', 'sniffio', functional))
