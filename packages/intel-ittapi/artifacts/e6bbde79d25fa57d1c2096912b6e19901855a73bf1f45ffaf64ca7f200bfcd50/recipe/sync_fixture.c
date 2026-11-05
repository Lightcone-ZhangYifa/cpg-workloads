#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define INTEL_NO_MACRO_BODY
#include "ittnotify.h"
void __itt_sync_create(void *address, const char *type, const char *name, int attribute) {
    if ((uintptr_t)address != UINT64_C(0x12345678abcdef01) || type != NULL ||
        strcmp(name, "cpg-sync") || attribute != 2) abort();
    puts("sync-create:64-bit-address:null-type:cpg-sync:mutex");
}
void (*__itt_sync_create_ptr__3_0)(void *, const char *, const char *, int) = __itt_sync_create;
