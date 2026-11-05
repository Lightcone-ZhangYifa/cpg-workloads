#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib-ng.h>

#define REQUIRE(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(int argc, char **argv) {
    enum { SIZE = 65536 };
    unsigned char data[SIZE], restored[SIZE];
    size_t capacity = zng_compressBound(SIZE) + 64, cases = 0;
    unsigned char *compressed = malloc(capacity);
    Dl_info library;
    REQUIRE(argc == 2 && compressed && strcmp(zlibng_version(), "2.3.3") == 0);
    REQUIRE(dladdr((void *)zlibng_version, &library) != 0);
    REQUIRE(zng_crc32(0, (const unsigned char *)"123456789", 9) == 0xcbf43926U);
    REQUIRE(zng_adler32(1, (const unsigned char *)"123456789", 9) == 0x091e01deU);
    for (size_t i = 0; i < SIZE; ++i) data[i] = (unsigned char)((i * 17 + i / 257) % 251);
    const size_t lengths[] = {0, 1, 16, 4096, SIZE};
    const int levels[] = {1, 6, 9};
    for (size_t i = 0; i < sizeof(lengths) / sizeof(lengths[0]); ++i) {
        for (size_t j = 0; j < sizeof(levels) / sizeof(levels[0]); ++j, ++cases) {
            size_t size = capacity, actual = SIZE, n = lengths[i];
            REQUIRE(zng_compress2(compressed, &size, data, n, levels[j]) == Z_OK);
            REQUIRE(zng_uncompress(restored, &actual, compressed, size) == Z_OK && actual == n && memcmp(data, restored, n) == 0);
            actual = SIZE;
            REQUIRE(zng_uncompress(restored, &actual, compressed, size - 1) != Z_OK);
            compressed[0] ^= 0xff;
            actual = SIZE;
            REQUIRE(zng_uncompress(restored, &actual, compressed, size) == Z_DATA_ERROR);
        }
    }
    zng_stream encoder = {0}, decoder = {0};
    REQUIRE(zng_deflateInit(&encoder, 6) == Z_OK);
    REQUIRE(zng_deflateSetDictionary(&encoder, data, 4096) == Z_OK);
    encoder.next_in = data; encoder.avail_in = SIZE;
    encoder.next_out = compressed; encoder.avail_out = (uint32_t)capacity;
    REQUIRE(zng_deflate(&encoder, Z_FINISH) == Z_STREAM_END);
    size_t encoded = encoder.total_out;
    REQUIRE(zng_deflateEnd(&encoder) == Z_OK);
    REQUIRE(zng_inflateInit(&decoder) == Z_OK);
    decoder.next_in = compressed; decoder.avail_in = (uint32_t)encoded;
    decoder.next_out = restored; decoder.avail_out = SIZE;
    REQUIRE(zng_inflate(&decoder, Z_FINISH) == Z_NEED_DICT);
    REQUIRE(zng_inflateSetDictionary(&decoder, (const unsigned char *)"wrong", 5) == Z_DATA_ERROR);
    REQUIRE(zng_inflateSetDictionary(&decoder, data, 4096) == Z_OK);
    REQUIRE(zng_inflate(&decoder, Z_FINISH) == Z_STREAM_END);
    REQUIRE(decoder.total_out == SIZE && memcmp(data, restored, SIZE) == 0);
    REQUIRE(zng_inflateEnd(&decoder) == Z_OK);
    memset(&encoder, 0, sizeof(encoder)); memset(&decoder, 0, sizeof(decoder));
    REQUIRE(zng_deflateInit2(&encoder, 6, Z_DEFLATED, 15 + 16, 8, Z_DEFAULT_STRATEGY) == Z_OK);
    encoder.next_in = data; encoder.avail_in = 123;
    encoder.next_out = compressed; encoder.avail_out = (uint32_t)capacity;
    REQUIRE(zng_deflate(&encoder, Z_NO_FLUSH) == Z_OK && encoder.avail_in == 0);
    encoder.next_in = data + 123; encoder.avail_in = SIZE - 123;
    REQUIRE(zng_deflate(&encoder, Z_FINISH) == Z_STREAM_END);
    encoded = encoder.total_out;
    REQUIRE(zng_deflateEnd(&encoder) == Z_OK);
    REQUIRE(zng_inflateInit2(&decoder, 15 + 32) == Z_OK);
    decoder.next_in = compressed; decoder.avail_in = (uint32_t)encoded;
    decoder.next_out = restored; decoder.avail_out = SIZE;
    REQUIRE(zng_inflate(&decoder, Z_FINISH) == Z_STREAM_END);
    REQUIRE(decoder.total_out == SIZE && memcmp(data, restored, SIZE) == 0 && zng_inflateEnd(&decoder) == Z_OK);
    gzFile file = zng_gzopen(argv[1], "wb6");
    REQUIRE(file && zng_gzwrite(file, data, SIZE) == SIZE && zng_gzclose(file) == Z_OK);
    file = zng_gzopen(argv[1], "rb");
    REQUIRE(file && zng_gzread(file, restored, SIZE) == SIZE && memcmp(data, restored, SIZE) == 0);
    unsigned char extra;
    REQUIRE(zng_gzread(file, &extra, 1) == 0 && zng_gzeof(file) && zng_gzclose(file) == Z_OK);
    free(compressed);
#ifdef CPG_STATIC_LIBRARY
    const char *linkage = "static";
#else
    const char *linkage = "shared";
#endif
    printf("version=2.3.3\nlinkage=%s\none_shot_cases=%zu\nchecksums=passed\ndictionary=passed\nstreaming=passed\ngz_file_io=passed\nlibrary=%s\n", linkage, cases, library.dli_fname);
    return 0;
}
