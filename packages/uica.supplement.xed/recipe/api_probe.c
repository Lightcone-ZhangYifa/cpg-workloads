#include <stdio.h>
#include <string.h>
#include "xed/xed-interface.h"

int main(void) {
    const xed_uint8_t mov[] = {0x48, 0x89, 0xd8};
    const xed_uint8_t truncated[] = {0x0f};
    xed_state_t state;
    xed_decoded_inst_t instruction;
    xed_uint8_t encoded[15];
    unsigned encoded_length = 0;
    xed_tables_init();
    xed_state_init2(&state, XED_MACHINE_MODE_LONG_64, XED_ADDRESS_WIDTH_64b);
    xed_decoded_inst_zero_set_mode(&instruction, &state);
    if (xed_decode(&instruction, mov, sizeof mov) != XED_ERROR_NONE) return 11;
    if (xed_decoded_inst_get_iclass(&instruction) != XED_ICLASS_MOV) return 12;
    if (xed_decoded_inst_get_length(&instruction) != 3) return 13;
    if (xed_decoded_inst_get_reg(&instruction, XED_OPERAND_REG0) != XED_REG_RAX) return 14;
    if (xed_decoded_inst_get_reg(&instruction, XED_OPERAND_REG1) != XED_REG_RBX) return 15;
    xed_encoder_request_init_from_decode(&instruction);
    if (xed_encode(&instruction, encoded, sizeof encoded, &encoded_length) != XED_ERROR_NONE) return 16;
    if (encoded_length != sizeof mov || memcmp(encoded, mov, sizeof mov)) return 17;
    xed_decoded_inst_zero_set_mode(&instruction, &state);
    if (xed_decode(&instruction, truncated, sizeof truncated) != XED_ERROR_BUFFER_TOO_SHORT) return 18;
    puts("XED installed C API: MOV registers, encode roundtrip and truncated-input rejection passed");
    return 0;
}
