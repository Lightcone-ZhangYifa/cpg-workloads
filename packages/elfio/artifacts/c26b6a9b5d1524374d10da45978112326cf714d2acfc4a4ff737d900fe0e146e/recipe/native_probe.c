#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#ifdef USE_XED
# include <xed/xed-interface.h>
#else
# include <Zydis/Zydis.h>
#endif

/* Tiny client of the actual public library; no instruction decoder here. */
int main(int argc, char **argv) {
    unsigned char b[32], out[32]; unsigned n=0;
    if(argc!=3 || strlen(argv[2])%2 || strlen(argv[2])>30) return 3;
    int mode=atoi(argv[1]);
    if(mode!=16 && mode!=32 && mode!=64) return 3;
    for(const char *p=argv[2]; *p; p+=2) {
        unsigned v; char s[3]={p[0],p[1],0};
        if(sscanf(s,"%x",&v)!=1) return 3;
        b[n++]=(unsigned char)v;
    }
    unsigned consumed=0, encoded=0; const char *name;
#ifdef USE_XED
    xed_tables_init();
    xed_state_t st;
    xed_state_init2(&st, mode==64?XED_MACHINE_MODE_LONG_64:mode==32?XED_MACHINE_MODE_LEGACY_32:XED_MACHINE_MODE_LEGACY_16,
                         mode==64?XED_ADDRESS_WIDTH_64b:mode==32?XED_ADDRESS_WIDTH_32b:XED_ADDRESS_WIDTH_16b);
    xed_decoded_inst_t inst;
    xed_decoded_inst_zero_set_mode(&inst,&st);
    xed_error_enum_t err=xed_decode(&inst,b,n);
    if(err!=XED_ERROR_NONE){fprintf(stderr,"decode rejected: %s\n",xed_error_enum_t2str(err));return 2;}
    consumed=xed_decoded_inst_get_length(&inst);
    name=xed_iclass_enum_t2str(xed_decoded_inst_get_iclass(&inst));
    xed_encoder_request_init_from_decode(&inst);
    err=xed_encode(&inst,out,sizeof(out),&encoded);
    if(err!=XED_ERROR_NONE){fprintf(stderr,"encode rejected: %s\n",xed_error_enum_t2str(err));return 4;}
#else
    ZydisDecoder decoder; ZydisDecodedInstruction inst;
    ZydisDecodedOperand ops[ZYDIS_MAX_OPERAND_COUNT];
    if(!ZYAN_SUCCESS(ZydisDecoderInit(&decoder, mode==64?ZYDIS_MACHINE_MODE_LONG_64:mode==32?ZYDIS_MACHINE_MODE_LEGACY_32:ZYDIS_MACHINE_MODE_LEGACY_16,
                         mode==64?ZYDIS_STACK_WIDTH_64:mode==32?ZYDIS_STACK_WIDTH_32:ZYDIS_STACK_WIDTH_16))) return 5;
    if(!ZYAN_SUCCESS(ZydisDecoderDecodeFull(&decoder,b,n,&inst,ops))){fprintf(stderr,"decode rejected\n");return 2;}
    ZydisEncoderRequest req;
    if(!ZYAN_SUCCESS(ZydisEncoderDecodedInstructionToEncoderRequest(&inst,ops,inst.operand_count_visible,&req))) return 4;
    ZyanUSize outlen=sizeof(out);
    if(!ZYAN_SUCCESS(ZydisEncoderEncodeInstruction(&req,out,&outlen))) return 4;
    consumed=inst.length;encoded=(unsigned)outlen;name=ZydisMnemonicGetString(inst.mnemonic);
#endif
    printf("{\"mnemonic\":\"%s\",\"length\":%u,\"encoded\":\"",name,consumed);
    for(unsigned i=0;i<encoded;i++)printf("%02x",out[i]);
    puts("\"}");return 0;
}
