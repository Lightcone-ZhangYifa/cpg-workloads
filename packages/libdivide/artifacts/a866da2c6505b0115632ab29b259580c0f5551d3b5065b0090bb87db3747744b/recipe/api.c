#include <inttypes.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include "libdivide.h"

#define CHECK_UNSIGNED(TAG, TYPE, MAXIMUM)                                      \
    do {                                                                      \
        TYPE numerators[] = {0, 1, 2, 7, 31, (MAXIMUM) / 2, (MAXIMUM) - 1, (MAXIMUM)}; \
        TYPE denominators[] = {1, 2, 3, 7, 31, (MAXIMUM) / 2 + 1, (MAXIMUM)};   \
        for (unsigned d = 0; d < sizeof denominators / sizeof *denominators; ++d) { \
            struct libdivide_##TAG##_t divisor = libdivide_##TAG##_gen(denominators[d]); \
            if (libdivide_##TAG##_recover(&divisor) != denominators[d]) return 1; \
            for (unsigned n = 0; n < sizeof numerators / sizeof *numerators; ++n) { \
                if (libdivide_##TAG##_do(numerators[n], &divisor) != numerators[n] / denominators[d]) return 2; \
                ++checks;                                                     \
            }                                                                 \
            if (denominators[d] != 1) {                                        \
                struct libdivide_##TAG##_branchfree_t bf = libdivide_##TAG##_branchfree_gen(denominators[d]); \
                for (unsigned n = 0; n < sizeof numerators / sizeof *numerators; ++n) { \
                    if (libdivide_##TAG##_branchfree_do(numerators[n], &bf) != numerators[n] / denominators[d]) return 3; \
                    ++checks;                                                 \
                }                                                             \
            }                                                                 \
        }                                                                     \
    } while (0)

#define CHECK_SIGNED(TAG, TYPE, MINIMUM, MAXIMUM)                               \
    do {                                                                      \
        TYPE numerators[] = {(MINIMUM), (MINIMUM) + 1, -100, -1, 0, 1, 100, (MAXIMUM) - 1, (MAXIMUM)}; \
        TYPE denominators[] = {(MINIMUM), -31, -1, 1, 2, 3, 7, (MAXIMUM)};       \
        for (unsigned d = 0; d < sizeof denominators / sizeof *denominators; ++d) { \
            struct libdivide_##TAG##_t divisor = libdivide_##TAG##_gen(denominators[d]); \
            struct libdivide_##TAG##_branchfree_t bf = libdivide_##TAG##_branchfree_gen(denominators[d]); \
            if (libdivide_##TAG##_recover(&divisor) != denominators[d]) return 4; \
            for (unsigned n = 0; n < sizeof numerators / sizeof *numerators; ++n) { \
                if (numerators[n] == (MINIMUM) && denominators[d] == -1) continue; \
                TYPE expected = numerators[n] / denominators[d];               \
                if (libdivide_##TAG##_do(numerators[n], &divisor) != expected || \
                    libdivide_##TAG##_branchfree_do(numerators[n], &bf) != expected) return 5; \
                checks += 2;                                                  \
            }                                                                 \
        }                                                                     \
    } while (0)

int main(void) {
    unsigned checks = 0;
    CHECK_UNSIGNED(u16, uint16_t, UINT16_MAX);
    CHECK_UNSIGNED(u32, uint32_t, UINT32_MAX);
    CHECK_UNSIGNED(u64, uint64_t, UINT64_MAX);
    CHECK_SIGNED(s16, int16_t, INT16_MIN, INT16_MAX);
    CHECK_SIGNED(s32, int32_t, INT32_MIN, INT32_MAX);
    CHECK_SIGNED(s64, int64_t, INT64_MIN, INT64_MAX);
    printf("libdivide C %s: %u comparisons passed\n", LIBDIVIDE_VERSION, checks);
    return 0;
}
