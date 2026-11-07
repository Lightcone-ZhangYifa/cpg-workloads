/* CPG acceptance fixture: construct SSA IR directly, then emit x86-64 assembly. */
#include <stdio.h>
#include <stdlib.h>
#include <libfirm/firm.h>

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    ir_init_library();
    if (!ir_target_set("x86_64-linux-gnu")) return 3;
    ir_target_init();

    ir_type *i32 = new_type_primitive(mode_Is);
    ir_type *signature = new_type_method(1, 1, 0, 0, mtp_no_property);
    set_method_param_type(signature, 0, i32);
    set_method_res_type(signature, 0, i32);
    ir_entity *entity = new_entity(get_glob_type(), new_id_from_str("cpg_affine"), signature);
    set_entity_visibility(entity, ir_visibility_external);
    set_entity_ld_ident(entity, new_id_from_str("cpg_affine"));
    ir_graph *graph = new_ir_graph(entity, 1);
    ir_node *block = get_r_cur_block(graph);
    ir_node *x = new_r_Proj(get_irg_args(graph), mode_Is, 0);
    ir_node *three = new_r_Const_long(graph, mode_Is, 3);
    ir_node *five = new_r_Const_long(graph, mode_Is, 5);
    ir_node *scaled = new_r_Mul(block, x, three);
    ir_node *answer = new_r_Add(block, scaled, five);
    ir_node *ret = new_r_Return(block, get_irg_initial_mem(graph), 1, &answer);
    add_immBlock_pred(get_irg_end_block(graph), ret);
    irg_finalize_cons(graph);
    if (!irg_verify(graph)) return 4;
    be_lower_for_target();
    FILE *output = fopen(argv[1], "w");
    if (output == NULL) return 5;
    be_main(output, "cpg-direct-ir");
    if (fclose(output) != 0) return 6;
    ir_finish();
    return 0;
}
