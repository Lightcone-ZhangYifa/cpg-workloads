/* CPG OpenACC adapter, not an upstream EPCC source modification. */
#include <errno.h>
#include <limits.h>
#include <math.h>
#include <openacc.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "level1.h"
#include "27stencil.h"
#include "himeno.h"

#ifndef _OPENACC
#error An actual OpenACC compiler mode is required
#endif

unsigned int datasize;

static int number(const char *s, unsigned long min, unsigned long max, unsigned long *value) {
    char *end = NULL;
    if (!s || !*s || *s == '-' || *s == '+') return 0;
    errno = 0;
    unsigned long parsed = strtoul(s, &end, 10);
    if (errno || *end || parsed < min || parsed > max) return 0;
    *value = parsed;
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 4) {
        fprintf(stderr, "usage: epcc-openacc-kernel KERNEL DATASIZE_BYTES SEED\n");
        return 64;
    }
    unsigned long bytes, seed;
    if (!number(argv[2], 65536, 16777216, &bytes) || !number(argv[3], 0, UINT32_MAX, &seed)) {
        fprintf(stderr, "invalid bounded datasize or seed\n");
        return 64;
    }
    datasize = (unsigned int)bytes;
    srand((unsigned int)seed);
    acc_set_device_type(acc_device_host);
    struct entry {const char *name; double (*function)(void);};
    const struct entry entries[] = {
        {"2MM",twomm}, {"3MM",threemm}, {"ATAX",atax}, {"BICG",bicg}, {"MVT",mvt},
        {"SYRK",syrk}, {"COV",covariance}, {"COR",correlation}, {"SYR2K",syr2k},
        {"GESUMMV",gesummv}, {"GEMM",gemm}, {"2DCONV",twodconv}, {"3DCONV",threedconv},
        {"27S",stencil}, {"HIMENO",himeno_main}
    };
    for (unsigned int i = 0; i < sizeof(entries) / sizeof(*entries); ++i) {
        if (!strcmp(argv[1], entries[i].name)) {
            const double seconds = entries[i].function();
            if (!isfinite(seconds)) {
                fprintf(stderr, "non-finite workload result\n");
                return 1;
            }
            printf("{\"kernel\":\"%s\",\"seconds\":%.17g,\"openacc\":%d,"
                   "\"device_type\":%d,\"host_device_type\":%d,\"datasize_bytes\":%u,\"seed\":%lu}\n",
                   argv[1], seconds, _OPENACC, (int)acc_get_device_type(),
                   (int)acc_device_host, datasize, seed);
            return seconds == -10000 || seconds == -11000 ? 1 : 0;
        }
    }
    fprintf(stderr, "kernel outside the qualified profile\n");
    return 65;
}
