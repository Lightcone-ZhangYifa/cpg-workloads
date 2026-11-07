#include <xbyak/xbyak.h>
#include <cstdio>
extern "C" int cpg_host_double(int v) { return 2*v; }
struct AbsPlus7 : Xbyak::CodeGenerator {
  AbsPlus7() { Xbyak::Label positive; mov(eax,edi); test(eax,eax); jge(positive); neg(eax); L(positive); add(eax,7); ret(); ready(); }
};
struct ExternalCall : Xbyak::CodeGenerator {
  ExternalCall() { mov(rax,(size_t)&cpg_host_double); jmp(rax); ready(); }
};
struct EncodingOnly : Xbyak::CodeGenerator {
  EncodingOnly() { vaddps(zmm0,zmm1,zmm2); ret(); }
};
int main() {
  AbsPlus7 a; ExternalCall c; EncodingOnly e;
  auto f=a.getCode<int(*)(int)>();auto g=c.getCode<int(*)(int)>();
  for(int x=-1000;x<=1000;x++) if(f(x)!=(x<0?-x:x)+7 || g(x)!=2*x)return 1;
  if(e.getSize()!=7 || e.getCode()[0]!=0x62)return 2;
  std::printf("XBYAK_PASS host=x86_64-sysv inputs=2001 external_symbol=1 avx512_encoding_only_bytes=%zu avx512_executed=0\n",e.getSize());
}
