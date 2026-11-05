/* Exercise the public libpfm4 API without opening any performance counter. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <perfmon/pfmlib.h>
#include <perfmon/pfmlib_perf_event.h>

static void json_string(const char *text)
{
    const unsigned char *p = (const unsigned char *)text;
    putchar('"');
    for (; *p; ++p) {
        if (*p == '"' || *p == '\\') { putchar('\\'); putchar(*p); }
        else if (*p < 32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

int main(void)
{
    static const struct { const char *name; unsigned type; uint64_t config; } events[] = {
        {"PERF_COUNT_HW_CPU_CYCLES", PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES},
        {"PERF_COUNT_HW_INSTRUCTIONS", PERF_TYPE_HARDWARE, PERF_COUNT_HW_INSTRUCTIONS},
        {"PERF_COUNT_SW_TASK_CLOCK", PERF_TYPE_SOFTWARE, PERF_COUNT_SW_TASK_CLOCK}
    };
    unsigned supported = 0, detected = 0;
    int version = pfm_get_version();
#ifndef CPG_STATIC_PROBE
    Dl_info library;
    if (!dladdr((void *)pfm_get_version, &library)) {
        fputs("Cannot resolve the shared library location\n", stderr);
        return 1;
    }
#endif
    if (version != LIBPFM_VERSION) {
        fputs("Header/library API version mismatch or unresolved library location\n", stderr);
        return 1;
    }
    int result = pfm_initialize();
    if (result != PFM_SUCCESS) {
        fprintf(stderr, "pfm_initialize: %s\n", pfm_strerror(result));
        return 1;
    }
    for (pfm_pmu_t pmu = PFM_PMU_NONE; pmu < PFM_PMU_MAX; ++pmu) {
        pfm_pmu_info_t info = {0};
        info.size = sizeof(info);
        if (pfm_get_pmu_info(pmu, &info) == PFM_SUCCESS) {
            ++supported;
            if (info.is_present) ++detected;
        }
    }
    if (!supported) { fputs("No PMU descriptions available\n", stderr); return 1; }
    for (size_t i = 0; i < sizeof(events)/sizeof(events[0]); ++i) {
        struct perf_event_attr attr = {0};
        char *qualified = NULL;
        pfm_perf_encode_arg_t arg = {0};
        attr.size = sizeof(attr);
        arg.size = sizeof(arg);
        arg.attr = &attr;
        arg.fstr = &qualified;
        result = pfm_get_os_event_encoding(events[i].name, PFM_PLM3, PFM_OS_PERF_EVENT_EXT, &arg);
        if (result != PFM_SUCCESS || attr.type != events[i].type || attr.config != events[i].config
                || !qualified || arg.idx < 0) {
            fprintf(stderr, "Event encoding mismatch for %s: %s\n", events[i].name, pfm_strerror(result));
            free(qualified);
            pfm_terminate();
            return 1;
        }
        pfm_event_info_t info = {0};
        info.size = sizeof(info);
        result = pfm_get_event_info(arg.idx, PFM_OS_PERF_EVENT_EXT, &info);
        free(qualified);
        if (result != PFM_SUCCESS || !info.name) {
            fputs("Encoded event identity cannot be queried\n", stderr);
            pfm_terminate();
            return 1;
        }
    }
    struct perf_event_attr invalid_attr = {0};
    pfm_perf_encode_arg_t invalid = {0};
    invalid_attr.size = sizeof(invalid_attr);
    invalid.size = sizeof(invalid);
    invalid.attr = &invalid_attr;
    result = pfm_get_os_event_encoding("CPG_INTENTIONALLY_INVALID_EVENT_6e73", PFM_PLM3,
                                      PFM_OS_PERF_EVENT_EXT, &invalid);
    if (result != PFM_ERR_NOTFOUND) {
        fprintf(stderr, "Invalid event was not rejected: %d\n", result);
        pfm_terminate();
        return 1;
    }
    pfm_terminate();
    printf("{\"api_version\":\"%u.%u\",\"supported_pmus\":%u,\"detected_pmus\":%u,"
           "\"encoded_events\":3,\"invalid_event_rejected\":true,\"counter_collection_qualified\":false,"
           "\"library_path\":", PFM_MAJ_VERSION(version), PFM_MIN_VERSION(version), supported, detected);
#ifdef CPG_STATIC_PROBE
    json_string("static");
#else
    json_string(library.dli_fname);
#endif
    puts("}");
    return 0;
}
