/* Read-only LIKWID topology, NUMA and performance-group API exercise. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <likwid.h>

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
    if (!dladdr((void *)topology_init,&library) || !library.dli_fname) return 1;
    if (topology_init()!=0 || numa_init()!=0) return 2;
    CpuTopology_t topo=get_cpuTopology();
    CpuInfo_t info=get_cpuInfo();
    NumaTopology_t numa=get_numaTopology();
    if (!topo || !info || !numa || topo->numHWThreads<1 || topo->numSockets<1 || numa->numberOfNodes<1) return 3;
    GroupInfo group;
    if (perfgroup_new(&group)!=0 || perfgroup_setGroupName(&group,"CPG_READ_ONLY")!=0) return 4;
    if (perfgroup_addEvent(&group,"PMC0","INSTR_RETIRED_ANY")!=0 || group.nevents!=1) return 5;
    if (perfgroup_addMetric(&group,"Instructions","PMC0")!=0 || group.nmetrics!=1) return 6;
    char *events=perfgroup_getEventStr(&group);
    if (!events || strcmp(events,"INSTR_RETIRED_ANY:PMC0")!=0) return 7;
    perfgroup_returnEventStr(events);
    if (perfgroup_removeEvent(&group,"PMC0")!=0 || group.nevents!=0) return 8;
    perfgroup_returnGroup(&group);
    printf("CPG_JSON={\"hardware_threads\":%u,\"active_threads\":%u,\"sockets\":%u,\"numa_nodes\":%u,"
           "\"group_roundtrip\":true,\"counter_collection_qualified\":false,\"library_path\":",
           topo->numHWThreads,topo->activeHWThreads,topo->numSockets,numa->numberOfNodes);
    json_string(library.dli_fname);puts("}");
    numa_finalize();topology_finalize();
    return 0;
}
