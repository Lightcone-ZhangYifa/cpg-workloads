#include "dr_api.h"
static uint64 count;
static void count_block(void) { ++count; }
static void finish(void) { dr_fprintf(STDERR, "CPG_BB_COUNT=%llu\n", (unsigned long long)count); }
static dr_emit_flags_t instrument(void *ctx, void *tag, instrlist_t *bb, bool trace, bool translate) {
    instr_t *first = instrlist_first_app(bb);
    if (first != NULL) dr_insert_clean_call(ctx, bb, first, (void *)count_block, false, 0);
    return DR_EMIT_DEFAULT;
}
DR_EXPORT void dr_client_main(client_id_t id, int argc, const char *argv[]) {
    dr_set_client_name("CPG controlled program basic-block events", "https://dynamorio.org/");
    dr_register_exit_event(finish);
    dr_register_bb_event(instrument);
}
