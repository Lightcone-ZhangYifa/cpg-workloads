/* SPDX-License-Identifier: MIT
 * Uses the pinned 20210528 consumer ABI. This is intentionally not compiled
 * against the incompatible signatures shown in newer libdwarf releases.
 */
#include <libdwarf/dwarf.h>
#include <libdwarf/libdwarf.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int visit(Dwarf_Debug debug, Dwarf_Die first, const char *wanted, int *found) {
    Dwarf_Die current = first;
    Dwarf_Error error = 0;
    for (;;) {
        Dwarf_Half tag = 0;
        if (dwarf_tag(current, &tag, &error) != DW_DLV_OK) return 1;
        char *name = NULL;
        int code = dwarf_diename(current, &name, &error);
        if (code == DW_DLV_ERROR) return 2;
        if (code == DW_DLV_OK) {
            printf("tag=%u name=%s\n", (unsigned)tag, name);
            if (!strcmp(name, wanted)) ++*found;
            dwarf_dealloc(debug, name, DW_DLA_STRING);
        }
        Dwarf_Die child = 0;
        code = dwarf_child(current, &child, &error);
        if (code == DW_DLV_ERROR) return 3;
        if (code == DW_DLV_OK && visit(debug, child, wanted, found)) return 4;
        Dwarf_Die sibling = 0;
        code = dwarf_siblingof_b(debug, current, 1, &sibling, &error);
        dwarf_dealloc_die(current);
        if (code == DW_DLV_NO_ENTRY) return 0;
        if (code == DW_DLV_ERROR) return 5;
        current = sibling;
    }
}

int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: dwarf_consume ELF EXPECTED_DIE_NAME\n"); return 2; }
    int fd = open(argv[1], O_RDONLY);
    if (fd < 0) { perror(argv[1]); return 3; }
    Dwarf_Debug debug = 0;
    Dwarf_Error error = 0;
    int code = dwarf_init_b(fd, DW_DLC_READ, DW_GROUPNUMBER_ANY, NULL, NULL, &debug, &error);
    if (code != DW_DLV_OK) {
        fprintf(stderr, "dwarf_init_b rejected input (%d): %s\n", code, error ? dwarf_errmsg(error) : "no DWARF");
        close(fd);
        return 4;
    }
    unsigned units = 0;
    int found = 0, failure = 0;
    for (;;) {
        Dwarf_Unsigned length, type_offset, next;
        Dwarf_Half version, address_size, length_size, extension_size, unit_type;
        Dwarf_Off abbrev;
        Dwarf_Sig8 signature;
        code = dwarf_next_cu_header_d(debug, 1, &length, &version, &abbrev,
            &address_size, &length_size, &extension_size, &signature,
            &type_offset, &next, &unit_type, &error);
        if (code == DW_DLV_NO_ENTRY) break;
        if (code != DW_DLV_OK) { failure = 1; break; }
        ++units;
        printf("unit=%u dwarf_version=%u address_size=%u\n", units, (unsigned)version, (unsigned)address_size);
        Dwarf_Die unit = 0;
        if (dwarf_siblingof_b(debug, NULL, 1, &unit, &error) != DW_DLV_OK ||
            visit(debug, unit, argv[2], &found)) { failure = 1; break; }
    }
    if (failure) fprintf(stderr, "DWARF parse failed: %s\n", error ? dwarf_errmsg(error) : "invalid DIE tree");
    printf("units=%u expected=%s matched=%d failure=%d\n", units, argv[2], found, failure);
    if (dwarf_finish(debug, &error) != DW_DLV_OK) failure = 1;
    close(fd);
    return failure || !units || !found ? 5 : 0;
}
