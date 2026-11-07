#include <libtcc.h>
#include <stdio.h>
static int calls;
static int cpg_host_add(int a,int b) {calls++;return a+b;}
int main(int argc,char **argv) {
  if(argc!=2)return 10;
  TCCState *s=tcc_new();if(!s)return 11;
  tcc_set_lib_path(s,argv[1]);
  if(tcc_set_output_type(s,TCC_OUTPUT_MEMORY)<0)return 12;
  const char *src="extern int cpg_host_add(int,int); int cpg_calc(int x) { if(x<0) return cpg_host_add(-x,7); return cpg_host_add(x,7); }";
  if(tcc_compile_string(s,src)<0)return 13;
  if(tcc_add_symbol(s,"cpg_host_add",cpg_host_add)<0)return 14;
  if(tcc_relocate(s)<0)return 15;
  int(*fn)(int)=tcc_get_symbol(s,"cpg_calc");if(!fn)return 16;
  for(int x=-1000;x<=1000;x++)if(fn(x)!=(x<0?-x:x)+7)return 17;
  if(calls!=2001)return 18;
  tcc_delete(s);
  printf("LIBTCC_PASS inputs=2001 host_callbacks=%d compiled_from_string=1\n",calls);
  return 0;
}
