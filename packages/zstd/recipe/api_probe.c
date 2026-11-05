#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zstd.h>

#define REQUIRE(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(void) {
    enum { SIZE = 65536 };
    unsigned char data[SIZE], restored[SIZE];
    size_t capacity = ZSTD_compressBound(SIZE), cases = 0;
    unsigned char *compressed = malloc(capacity);
    Dl_info library;
    REQUIRE(compressed && ZSTD_versionNumber() == 10507);
    REQUIRE(dladdr((void *)ZSTD_versionNumber, &library) != 0);
    for (size_t i = 0; i < SIZE; ++i) data[i] = (unsigned char)((i * 17 + i / 257) % 251);
    const size_t lengths[] = {0, 1, 127, 4096, SIZE};
    const int levels[] = {1, 3, 9};
    for (size_t i = 0; i < sizeof(lengths) / sizeof(lengths[0]); ++i) {
        for (size_t j = 0; j < sizeof(levels) / sizeof(levels[0]); ++j, ++cases) {
            size_t n = lengths[i];
            size_t size = ZSTD_compress(compressed, capacity, data, n, levels[j]);
            REQUIRE(!ZSTD_isError(size));
            REQUIRE(ZSTD_getFrameContentSize(compressed, size) == n);
            size_t actual = ZSTD_decompress(restored, SIZE, compressed, size);
            REQUIRE(!ZSTD_isError(actual) && actual == n && memcmp(data, restored, n) == 0);
            REQUIRE(ZSTD_isError(ZSTD_decompress(restored, SIZE, compressed, size - 1)));
            compressed[0] ^= 0xff;
            REQUIRE(ZSTD_isError(ZSTD_decompress(restored, SIZE, compressed, size)));
        }
    }
    ZSTD_CCtx *encoder = ZSTD_createCCtx();
    ZSTD_DCtx *decoder = ZSTD_createDCtx();
    REQUIRE(encoder && decoder);
    REQUIRE(!ZSTD_isError(ZSTD_CCtx_setParameter(encoder, ZSTD_c_nbWorkers, 2)));
    REQUIRE(!ZSTD_isError(ZSTD_CCtx_setParameter(encoder, ZSTD_c_checksumFlag, 1)));
    ZSTD_inBuffer input = {data, SIZE, 0};
    ZSTD_outBuffer output = {compressed, capacity, 0};
    size_t remaining;
    do {
        remaining = ZSTD_compressStream2(encoder, &output, &input, ZSTD_e_end);
        REQUIRE(!ZSTD_isError(remaining) && output.pos <= output.size);
        REQUIRE(remaining == 0 || output.pos < output.size);
    } while (remaining);
    REQUIRE(input.pos == SIZE);
    ZSTD_inBuffer encoded = {compressed, output.pos, 0};
    ZSTD_outBuffer decoded = {restored, SIZE, 0};
    do {
        size_t before_in = encoded.pos, before_out = decoded.pos;
        remaining = ZSTD_decompressStream(decoder, &decoded, &encoded);
        REQUIRE(!ZSTD_isError(remaining));
        REQUIRE(remaining == 0 || encoded.pos != before_in || decoded.pos != before_out);
    } while (remaining);
    REQUIRE(encoded.pos == encoded.size && decoded.pos == SIZE && memcmp(data, restored, SIZE) == 0);
    ZSTD_CDict *cdict = ZSTD_createCDict(data, 4096, 3);
    ZSTD_DDict *ddict = ZSTD_createDDict(data, 4096);
    REQUIRE(cdict && ddict);
    size_t size = ZSTD_compress_usingCDict(encoder, compressed, capacity, data, SIZE, cdict);
    REQUIRE(!ZSTD_isError(size));
    size_t actual = ZSTD_decompress_usingDDict(decoder, restored, SIZE, compressed, size, ddict);
    REQUIRE(!ZSTD_isError(actual) && actual == SIZE && memcmp(data, restored, SIZE) == 0);
    REQUIRE(!ZSTD_isError(ZSTD_freeCDict(cdict)) && !ZSTD_isError(ZSTD_freeDDict(ddict)));
    REQUIRE(!ZSTD_isError(ZSTD_freeCCtx(encoder)) && !ZSTD_isError(ZSTD_freeDCtx(decoder)));
    free(compressed);
    printf("version=1.5.7\none_shot_cases=%zu\nstreaming_workers=2\nraw_dictionary_roundtrip=passed\nlibrary=%s\n", cases, library.dli_fname);
    return 0;
}
