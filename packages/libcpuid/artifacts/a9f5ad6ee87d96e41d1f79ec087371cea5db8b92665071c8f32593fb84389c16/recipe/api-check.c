/* A bounded deployment check of the installed public API, not a benchmark. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
#include <libcpuid/libcpuid.h>

int main(void) {
#ifndef CPG_STATIC_PROBE
    Dl_info library;
    if (!dladdr((void *)cpuid_lib_version, &library) || !library.dli_fname) {
        fputs("Cannot identify the loaded package library\n", stderr);
        return 1;
    }
    printf("loaded_library=%s\n", library.dli_fname);
#else
    puts("link_mode=static");
#endif
    struct cpu_raw_data_t raw;
    struct cpu_id_t cpu;
    if (cpuid_get_raw_data(&raw) != 0 || cpu_identify(&raw, &cpu) != 0) {
        fprintf(stderr, "libcpuid identification failed: %s\n", cpuid_error());
        return 1;
    }
    if (strlen(cpu.vendor_str) == 0 || cpu.total_logical_cpus <= 0) {
        fputs("libcpuid returned an empty CPU identity\n", stderr);
        return 1;
    }
    printf("libcpuid API passed: version=%s vendor=%s logical_cpus=%d\n",
           cpuid_lib_version(), cpu.vendor_str, cpu.total_logical_cpus);
    return 0;
}
