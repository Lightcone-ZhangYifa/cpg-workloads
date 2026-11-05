/* Exercise PAPI component/event-set APIs without adding or starting counters. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <papi.h>

static void json_string(const char *text) {
    putchar('"');
    for (const unsigned char *p=(const unsigned char *)text; *p; ++p) {
        if (*p=='"' || *p=='\\') { putchar('\\'); putchar(*p); }
        else if (*p<32) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}

int main(void) {
    Dl_info library;
    if (!dladdr((void *)PAPI_library_init,&library) || !library.dli_fname) return 1;
    int version=PAPI_library_init(PAPI_VER_CURRENT);
    if (version!=PAPI_VER_CURRENT) return 2;
    int components=PAPI_num_components();
    if (components!=3 || !PAPI_get_hardware_info()) return 3;
    int eventset=PAPI_NULL;
    if (PAPI_create_eventset(&eventset)!=PAPI_OK || PAPI_num_events(eventset)!=0) return 4;
    if (PAPI_destroy_eventset(&eventset)!=PAPI_OK || eventset!=PAPI_NULL) return 5;
    int code=0;
    if (PAPI_event_name_to_code("CPG_INTENTIONALLY_INVALID_EVENT",&code)!=PAPI_ENOEVNT) return 6;
    long long first=PAPI_get_real_usec();
    long long second=PAPI_get_real_usec();
    if (first<0 || second<first) return 7;
    printf("CPG_JSON={\"version\":%d,\"components\":[",version);
    for (int i=0;i<components;++i) {
        const PAPI_component_info_t *component=PAPI_get_component_info(i);
        if (!component || !component->name[0]) return 8;
        if (i) putchar(',');
        printf("{\"name\":");json_string(component->name);
        printf(",\"disabled\":%d,\"disabled_reason\":",component->disabled);
        json_string(component->disabled_reason);putchar('}');
    }
    printf("],\"empty_eventset_lifecycle\":true,\"invalid_event_rejected\":true,"
           "\"monotonic_time\":true,\"counter_collection_qualified\":false,\"library_path\":");
    json_string(library.dli_fname);puts("}");
    PAPI_shutdown();
    return 0;
}
