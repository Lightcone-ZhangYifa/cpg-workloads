#define _GNU_SOURCE
#include <dlfcn.h>
#include <inttypes.h>
#include <lzma.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define REQUIRE(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(void) {
    enum { SIZE = 65536 };
    unsigned char data[SIZE], decoded[SIZE];
    size_t capacity = lzma_stream_buffer_bound(SIZE) + 4096;
    unsigned char *encoded = malloc(capacity);
    size_t cases = 0;
    Dl_info library;
    REQUIRE(encoded && strcmp(lzma_version_string(), "5.8.4") == 0);
    REQUIRE(lzma_version_number() == LZMA_VERSION);
    REQUIRE(dladdr((void *)lzma_version_string, &library) != 0);
    REQUIRE(lzma_crc32((const uint8_t *)"123456789", 9, 0) == UINT32_C(0xcbf43926));
    REQUIRE(lzma_crc64((const uint8_t *)"123456789", 9, 0) == UINT64_C(0x995dc9bbdf1939fa));
    for (size_t i = 0; i < SIZE; ++i) data[i] = (unsigned char)((i * 17 + i / 257) % 251);
    const size_t lengths[] = {0, 1, 31, 4096, SIZE};
    const uint32_t presets[] = {1, 6, 9};
    const lzma_check checks[] = {LZMA_CHECK_CRC32, LZMA_CHECK_CRC64, LZMA_CHECK_SHA256};
    for (size_t i = 0; i < sizeof(lengths) / sizeof(lengths[0]); ++i)
        for (size_t j = 0; j < sizeof(presets) / sizeof(presets[0]); ++j)
            for (size_t k = 0; k < sizeof(checks) / sizeof(checks[0]); ++k, ++cases) {
                size_t size = 0, consumed = 0, written = 0;
                uint64_t memory = UINT64_MAX;
                REQUIRE(lzma_check_is_supported(checks[k]));
                REQUIRE(lzma_easy_buffer_encode(presets[j], checks[k], NULL,
                            data, lengths[i], encoded, &size, capacity) == LZMA_OK);
                REQUIRE(lzma_stream_buffer_decode(&memory, 0, NULL, encoded, &consumed,
                            size, decoded, &written, SIZE) == LZMA_OK);
                REQUIRE(consumed == size && written == lengths[i] && memcmp(data, decoded, written) == 0);
                consumed = written = 0; memory = UINT64_MAX;
                REQUIRE(lzma_stream_buffer_decode(&memory, 0, NULL, encoded, &consumed,
                            size - 1, decoded, &written, SIZE) != LZMA_OK);
                encoded[size - 1] ^= 0xff;
                consumed = written = 0; memory = UINT64_MAX;
                REQUIRE(lzma_stream_buffer_decode(&memory, 0, NULL, encoded, &consumed,
                            size, decoded, &written, SIZE) != LZMA_OK);
                encoded[size - 1] ^= 0xff;
                if (lengths[i] != 0) {
                    consumed = written = 0; memory = 1;
                    REQUIRE(lzma_stream_buffer_decode(&memory, 0, NULL, encoded, &consumed,
                                size, decoded, &written, SIZE) == LZMA_MEMLIMIT_ERROR);
                }
            }
    size_t size = 0;
    REQUIRE(lzma_easy_buffer_encode(10, LZMA_CHECK_CRC64, NULL, data, SIZE,
                encoded, &size, capacity) == LZMA_OPTIONS_ERROR);

    lzma_options_lzma options;
    REQUIRE(!lzma_lzma_preset(&options, 6));
    lzma_filter filters[] = {{LZMA_FILTER_X86, NULL}, {LZMA_FILTER_LZMA2, &options}, {LZMA_VLI_UNKNOWN, NULL}};
    size = 0;
    REQUIRE(lzma_raw_buffer_encode(filters, NULL, data, SIZE, encoded, &size, capacity) == LZMA_OK);
    size_t consumed = 0, written = 0;
    REQUIRE(lzma_raw_buffer_decode(filters, NULL, encoded, &consumed, size,
                decoded, &written, SIZE) == LZMA_OK);
    REQUIRE(consumed == size && written == SIZE && memcmp(data, decoded, SIZE) == 0);

    lzma_stream stream = LZMA_STREAM_INIT;
    lzma_mt multithreaded = {0};
    multithreaded.threads = 2;
    multithreaded.block_size = 16384;
    multithreaded.preset = 6;
    multithreaded.check = LZMA_CHECK_CRC64;
    REQUIRE(lzma_stream_encoder_mt(&stream, &multithreaded) == LZMA_OK);
    stream.next_in = data; stream.avail_in = SIZE;
    stream.next_out = encoded; stream.avail_out = capacity;
    lzma_ret ret;
    do { ret = lzma_code(&stream, LZMA_FINISH); } while (ret == LZMA_OK);
    REQUIRE(ret == LZMA_STREAM_END && stream.total_in == SIZE);
    size = stream.total_out;
    lzma_end(&stream);
    uint64_t memory = UINT64_MAX;
    consumed = written = 0;
    REQUIRE(lzma_stream_buffer_decode(&memory, 0, NULL, encoded, &consumed,
                size, decoded, &written, SIZE) == LZMA_OK);
    REQUIRE(consumed == size && written == SIZE && memcmp(data, decoded, SIZE) == 0);
    free(encoded);
#ifdef CPG_STATIC_LIBRARY
    const char *linkage = "static";
#else
    const char *linkage = "shared";
#endif
    printf("version=5.8.4\nlinkage=%s\none_shot_cases=%zu\nfixed_crc_vectors=passed\n"
           "truncation_and_corruption=passed\nmemory_limit_rejection=passed\ninvalid_preset=passed\n"
           "raw_x86_lzma2_filters=passed\nmultithreaded_encoder_threads=2\nlibrary=%s\n", linkage, cases, library.dli_fname);
    return 0;
}
