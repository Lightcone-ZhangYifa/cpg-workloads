/* Verify the installed C API against the process-visible topology. */
#include <stdio.h>
#include <hwloc.h>

int main(void) {
    hwloc_topology_t topology;
    if (hwloc_topology_init(&topology) != 0) return 1;
    if (hwloc_topology_load(topology) != 0) {
        hwloc_topology_destroy(topology);
        return 1;
    }
    int pus = hwloc_get_nbobjs_by_type(topology, HWLOC_OBJ_PU);
    int allowed = hwloc_bitmap_weight(hwloc_topology_get_allowed_cpuset(topology));
    if (pus <= 0 || allowed <= 0) {
        fputs("hwloc returned an empty processing-unit or allowed CPU set\n", stderr);
        hwloc_topology_destroy(topology);
        return 1;
    }
    printf("hwloc API passed: api=%u processing_units=%d allowed_cpus=%d\n",
           hwloc_get_api_version(), pus, allowed);
    hwloc_topology_destroy(topology);
    return 0;
}
