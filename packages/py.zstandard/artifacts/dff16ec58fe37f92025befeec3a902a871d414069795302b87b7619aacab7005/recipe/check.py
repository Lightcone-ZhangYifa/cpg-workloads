#!/usr/bin/env python3
"""Installed functional check for zstandard; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(zstd, work):
    """Round-trip real frames through multiple APIs and detect damaged data."""
    import io
    data = bytes(range(256))*127 + b"compiler playground"
    compressor = zstd.ZstdCompressor(level=3, write_checksum=True)
    frame = compressor.compress(data)
    decompressor = zstd.ZstdDecompressor()
    require(decompressor.decompress(frame) == data, "Frame round trip mismatch")
    with decompressor.stream_reader(io.BytesIO(frame)) as stream:
        require(stream.read() == data, "Stream decompression mismatch")
    obj = decompressor.decompressobj()
    pieces = [obj.decompress(frame[i:i+7]) for i in range(0, len(frame), 7)]
    pieces.append(obj.flush())
    require(b"".join(pieces) == data and obj.eof, "Incremental decompression mismatch")
    damaged = frame[:-1] + bytes([frame[-1] ^ 1])
    raises(zstd.ZstdError, lambda: decompressor.decompress(damaged), "Checksum corruption was accepted")
    raises(zstd.ZstdError, lambda: decompressor.decompress(b"invalid"), "Invalid frame was accepted")
    return {"checks": ["checksum-frame-roundtrip", "stream-reader", "incremental-reader", "checksum-corruption", "invalid-frame"], "uncompressed_bytes": len(data), "compressed_bytes": len(frame)}

if __name__ == "__main__":
    raise SystemExit(main('zstandard', 'zstandard', functional))
