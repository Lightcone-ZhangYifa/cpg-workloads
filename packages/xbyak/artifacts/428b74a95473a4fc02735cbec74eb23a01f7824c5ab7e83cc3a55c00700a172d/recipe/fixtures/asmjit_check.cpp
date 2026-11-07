#include <asmjit/x86.h>
#include <cstdio>
using namespace asmjit;
int main() {
  JitRuntime rt;
  CodeHolder code;
  if (code.init(rt.environment()) != Error::kOk) return 1;
  x86::Assembler a(&code);
  if (a.mov(x86::eax,x86::edi) != Error::kOk ||
      a.imul(x86::eax,x86::eax,3) != Error::kOk ||
      a.add(x86::eax,x86::esi) != Error::kOk || a.ret() != Error::kOk) return 2;
  using Fn = int(*)(int,int);
  Fn fn=nullptr;
  if (rt.add(&fn,&code) != Error::kOk || !fn) return 3;
  unsigned checked=0;
  for (int x=-1000;x<=1000;x++) for(int y=-3;y<=3;y++) {
    if (fn(x,y)!=3*x+y) return 4;
    checked++;
  }
  if (rt.release(fn)!=Error::kOk) return 5;
  std::printf("ASMJIT_PASS host=x86_64-sysv checked=%u runtime_memory_released=1\n",checked);
}
