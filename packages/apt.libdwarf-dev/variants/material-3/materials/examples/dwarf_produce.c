/* SPDX-License-Identifier: MIT
 * libdwarf 20210528 producer API, DWARF4 / ELF64 little endian.
 * Emits a compile unit with one subprogram and no addresses or relocations.
 * The runner adds the sections to a small ELF object using GNU objcopy.
 */
#include <libdwarf/dwarf.h>
#include <libdwarf/libdwarf.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct section_table { char names[32][128]; unsigned count; };

static int section_callback(const char *name, int size, Dwarf_Unsigned type,
        Dwarf_Unsigned flags, Dwarf_Unsigned link, Dwarf_Unsigned info,
        Dwarf_Unsigned *name_index, void *user, int *error) {
    struct section_table *table = user;
    (void)size; (void)type; (void)flags; (void)link; (void)info;
    if (table->count + 1 >= 32 || strlen(name) >= 128) {
        *error = 1;
        return -1;
    }
    unsigned index = ++table->count;
    strcpy(table->names[index], name);
    *name_index = index;
    return (int)index;
}

#define CHECK(call) do { \
    int code = (call); \
    if (code != DW_DLV_OK) { \
        fprintf(stderr, "%s failed (%d): %s\n", #call, code, error ? dwarf_errmsg(error) : "no detail"); \
        return 1; \
    } \
} while (0)

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: dwarf_produce OUTPUT_DIRECTORY\n"); return 2; }
    Dwarf_P_Debug debug = 0;
    Dwarf_Error error = 0;
    Dwarf_P_Die unit = 0, function = 0;
    Dwarf_P_Attribute attribute = 0;
    struct section_table table = {{{0}},0};
    Dwarf_Unsigned flags = DW_DLC_POINTER64 | DW_DLC_OFFSET32 |
        DW_DLC_TARGET_LITTLEENDIAN | DW_DLC_SYMBOLIC_RELOCATIONS;
    CHECK(dwarf_producer_init(flags, section_callback, NULL, NULL, &table,
                             "x86_64", "V4", "", &debug, &error));
    CHECK(dwarf_pro_set_default_string_form(debug, DW_FORM_string, &error));
    CHECK(dwarf_new_die_a(debug, DW_TAG_compile_unit, NULL, NULL, NULL, NULL, &unit, &error));
    CHECK(dwarf_add_AT_name_a(unit, "cpg_example_generated.c", &attribute, &error));
    CHECK(dwarf_add_AT_producer_a(unit, "CPG cpg_example libdwarf producer", &attribute, &error));
    CHECK(dwarf_add_AT_unsigned_const_a(debug, unit, DW_AT_language, DW_LANG_C99, &attribute, &error));
    CHECK(dwarf_new_die_a(debug, DW_TAG_subprogram, unit, NULL, NULL, NULL, &function, &error));
    CHECK(dwarf_add_AT_name_a(function, "generated_subprogram", &attribute, &error));
    CHECK(dwarf_add_die_to_debug_a(debug, unit, &error));
    Dwarf_Signed count = 0;
    CHECK(dwarf_transform_to_disk_form_a(debug, &count, &error));
    for (Dwarf_Signed buffer = 0; buffer < count; ++buffer) {
        Dwarf_Signed section = 0;
        Dwarf_Unsigned length = 0;
        Dwarf_Ptr bytes = NULL;
        CHECK(dwarf_get_section_bytes_a(debug, buffer, &section, &length, &bytes, &error));
        if (section <= 0 || section > table.count) return 3;
        char path[4096];
        if (snprintf(path, sizeof(path), "%s/%s", argv[1], table.names[section]) >= (int)sizeof(path)) return 4;
        FILE *output = fopen(path, "ab");
        if (!output) { perror(path); return 5; }
        if (fwrite(bytes, 1, (size_t)length, output) != (size_t)length) return 6;
        if (fclose(output)) return 7;
        printf("section=%s size=%llu\n", table.names[section], (unsigned long long)length);
    }
    CHECK(dwarf_producer_finish_a(debug, &error));
    return 0;
}
