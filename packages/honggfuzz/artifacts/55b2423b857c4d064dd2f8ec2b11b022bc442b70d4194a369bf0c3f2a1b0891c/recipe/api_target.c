#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "libhfuzz/libhfuzz.h"

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    const char *marker = getenv("CPG_HONGGFUZZ_MARKER");
    if (size == 4 && !memcmp(data, "GOOD", 4) && marker) {
        FILE *file = fopen(marker, "ab");
        if (!file) abort();
        fputc('G', file);
        fclose(file);
    }
    if (size == 4 && !memcmp(data, "CRSH", 4)) abort();
    return 0;
}
