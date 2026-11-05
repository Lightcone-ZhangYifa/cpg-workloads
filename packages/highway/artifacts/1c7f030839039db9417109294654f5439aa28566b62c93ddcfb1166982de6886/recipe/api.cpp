#include <cstdint>
#include <cstdio>
#include <vector>
#undef HWY_TARGET_INCLUDE
#define HWY_TARGET_INCLUDE "api.cpp"
#include "hwy/foreach_target.h"
#include "hwy/highway.h"

HWY_BEFORE_NAMESPACE();
namespace cpg {
namespace HWY_NAMESPACE {
namespace hn = hwy::HWY_NAMESPACE;
int64_t Transform(const uint32_t* input, uint32_t* output, size_t count) {
  const hn::ScalableTag<uint32_t> d;
  const size_t lanes = hn::Lanes(d);
  size_t i = 0;
  for (; i + lanes <= count; i += lanes) {
    auto x = hn::LoadU(d, input + i);
    hn::StoreU(hn::Add(hn::Mul(x, hn::Set(d, 7u)), hn::Set(d, 11u)), d, output + i);
  }
  for (; i < count; ++i) output[i] = input[i] * 7u + 11u;
  return HWY_TARGET;
}
}
}
HWY_AFTER_NAMESPACE();

#if HWY_ONCE
namespace cpg {
HWY_EXPORT(Transform);
int64_t CallTransform(const uint32_t* input, uint32_t* output, size_t count) {
  return HWY_DYNAMIC_DISPATCH(Transform)(input, output, count);
}
}
int main() {
  const size_t sizes[] = {0, 1, 3, 7, 15, 16, 17, 31, 63, 64, 65, 255, 1029};
  auto targets = hwy::SupportedAndGeneratedTargets();
  if (targets.empty()) return 10;
  for (int64_t target : targets) {
    hwy::SetSupportedTargetsForTest(target);
    int cases = 0;
    for (size_t count : sizes) {
      for (size_t offset : {size_t(0), size_t(1), size_t(3)}) {
        std::vector<uint32_t> input(count + offset + 8, 0x11223344u);
        std::vector<uint32_t> output(count + offset + 8, 0xdeadbeefu);
        for (size_t i = 0; i < count; ++i) input[offset+i] = uint32_t(i) * 123456789u;
        const int64_t actual = cpg::CallTransform(input.data()+offset, output.data()+offset, count);
        if (actual != target) return 11;
        for (size_t i = 0; i < count; ++i)
          if (output[offset+i] != input[offset+i]*7u+11u) return 12;
        for (size_t i = 0; i < offset; ++i) if (output[i] != 0xdeadbeefu) return 13;
        for (size_t i = offset+count; i < output.size(); ++i) if (output[i] != 0xdeadbeefu) return 14;
        ++cases;
      }
    }
    std::printf("%s %d\n", hwy::TargetName(target), cases);
  }
  hwy::SetSupportedTargetsForTest(0);
  return 0;
}
#endif
