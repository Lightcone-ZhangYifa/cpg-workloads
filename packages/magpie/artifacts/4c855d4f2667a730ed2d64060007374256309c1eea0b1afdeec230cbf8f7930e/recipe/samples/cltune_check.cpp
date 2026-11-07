#include <cltune.h>
#include <vector>
#include <string>
int main() {
  const size_t n=262144;
  std::vector<float> a(n),b(n),c(n,0.f);
  for(size_t i=0;i<n;++i) {a[i]=float(i%101);b[i]=float(i%13);}
  const std::string reference=R"CLC(
  __kernel void reference(const int n,__global const float*a,__global const float*b,__global float*c) {
    const int i=get_global_id(0);if(i<n)c[i]=a[i]+b[i];
  })CLC";
  const std::string kernel=R"CLC(
  __kernel void vector_add(const int n,__global const float*a,__global const float*b,__global float*c) {
    const int i=get_global_id(0);if(i<n)c[i]=a[i]+b[i]+BAD;
  })CLC";
  cltune::Tuner tuner(0,0);
  auto id=tuner.AddKernelFromString(kernel,"vector_add",{n},{1});
  tuner.SetReferenceFromString(reference,"reference",{n},{1});
  tuner.AddParameter(id,"GROUP_SIZE",{32,64,128,256});
  tuner.AddParameter(id,"BAD",{0,1});
  tuner.MulLocalSize(id,{"GROUP_SIZE"});
  tuner.AddArgumentScalar(static_cast<int>(n));
  tuner.AddArgumentInput(a);tuner.AddArgumentInput(b);tuner.AddArgumentOutput(c);
  tuner.SetNumRuns(3);tuner.Tune();tuner.PrintToScreen();tuner.PrintJSON("cltune-upstream.json",{});
  return 0;
}
