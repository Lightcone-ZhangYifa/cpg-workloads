#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <xxhash.h>

typedef uint8_t XSUM_U8;
typedef uint32_t XSUM_U32;
typedef uint64_t XSUM_U64;
/* Unmodified oracle from the exact upstream source archive. */
#include "sanity_test_vectors.h"

#define COUNT(a) (sizeof(a) / sizeof((a)[0]))
#define REQUIRE(c) do { if (!(c)) { fprintf(stderr, "failed line %d: %s\n", __LINE__, #c); return 1; } } while (0)

int main(void) {
    unsigned char data[4161 + 64];
    uint64_t value = UINT64_C(2654435761);
    size_t checked = 0;
    Dl_info library;
    REQUIRE(XXH_versionNumber() == 804);
    REQUIRE(dladdr((void *)XXH_versionNumber, &library) != 0);
    for (size_t i = 0; i < sizeof(data); ++i) {
        data[i] = (unsigned char)(value >> 56);
        value *= UINT64_C(11400714785074694797);
    }
    for (size_t i = 0; i < COUNT(XSUM_XXH32_testdata); ++i, ++checked) {
        const XSUM_testdata32_t *t = &XSUM_XXH32_testdata[i];
        REQUIRE(XXH32(data, t->len, t->seed) == t->Nresult);
    }
    for (size_t i = 0; i < COUNT(XSUM_XXH64_testdata); ++i, ++checked) {
        const XSUM_testdata64_t *t = &XSUM_XXH64_testdata[i];
        REQUIRE(XXH64(data, t->len, t->seed) == t->Nresult);
    }
    for (size_t i = 0; i < COUNT(XSUM_XXH3_testdata); ++i, ++checked) {
        const XSUM_testdata64_t *t = &XSUM_XXH3_testdata[i];
        REQUIRE(XXH3_64bits_withSeed(data, t->len, t->seed) == t->Nresult);
    }
    for (size_t i = 0; i < COUNT(XSUM_XXH128_testdata); ++i, ++checked) {
        const XSUM_testdata128_t *t = &XSUM_XXH128_testdata[i];
        XXH128_hash_t actual = XXH3_128bits_withSeed(data, t->len, t->seed);
        REQUIRE(actual.low64 == t->Nresult.low64 && actual.high64 == t->Nresult.high64);
    }
    /* Installed shared-library streaming APIs, including unaligned inputs. */
    const size_t lengths[] = {0, 1, 3, 16, 31, 64, 129, 240, 241, 1024, 4096};
    for (size_t offset = 0; offset < 32; ++offset) {
        for (size_t i = 0; i < COUNT(lengths); ++i) {
            const unsigned char *p = data + offset;
            size_t n = lengths[i], a = n / 3;
            XXH32_state_t *s32 = XXH32_createState();
            XXH64_state_t *s64 = XXH64_createState();
            XXH3_state_t *s3 = XXH3_createState();
            REQUIRE(s32 && s64 && s3);
            REQUIRE(XXH32_reset(s32, 17) == XXH_OK);
            REQUIRE(XXH32_update(s32, p, a) == XXH_OK && XXH32_update(s32, p + a, n - a) == XXH_OK);
            REQUIRE(XXH32_digest(s32) == XXH32(p, n, 17));
            REQUIRE(XXH64_reset(s64, 17) == XXH_OK);
            REQUIRE(XXH64_update(s64, p, a) == XXH_OK && XXH64_update(s64, p + a, n - a) == XXH_OK);
            REQUIRE(XXH64_digest(s64) == XXH64(p, n, 17));
            REQUIRE(XXH3_64bits_reset_withSeed(s3, 17) == XXH_OK);
            REQUIRE(XXH3_64bits_update(s3, p, a) == XXH_OK && XXH3_64bits_update(s3, p + a, n - a) == XXH_OK);
            REQUIRE(XXH3_64bits_digest(s3) == XXH3_64bits_withSeed(p, n, 17));
            REQUIRE(XXH3_128bits_reset_withSeed(s3, 17) == XXH_OK);
            REQUIRE(XXH3_128bits_update(s3, p, a) == XXH_OK && XXH3_128bits_update(s3, p + a, n - a) == XXH_OK);
            XXH128_hash_t actual = XXH3_128bits_digest(s3), expected = XXH3_128bits_withSeed(p, n, 17);
            REQUIRE(actual.low64 == expected.low64 && actual.high64 == expected.high64);
            REQUIRE(XXH32_freeState(s32) == XXH_OK && XXH64_freeState(s64) == XXH_OK && XXH3_freeState(s3) == XXH_OK);
        }
    }
    printf("version=0.8.4\nupstream_vectors=%zu\nstreaming_alignment_cases=%zu\nlibrary=%s\n", checked, 32 * COUNT(lengths) * 4, library.dli_fname);
    return 0;
}
