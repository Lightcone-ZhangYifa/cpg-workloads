// Application-level reuse fixture; requires the original Google Benchmark prefix.
// The preflight and volatile checksum make incorrect/dead work fail explicitly.
#include <benchmark/benchmark.h>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <vector>

static std::uint64_t sum(const std::vector<std::uint64_t>& data) {
  std::uint64_t result = 0;
  for (const auto value : data) result += value;
  return result;
}

static void BM_Empty(benchmark::State& state) {
  std::uint64_t live = 0;
  for (auto _ : state) {
    benchmark::DoNotOptimize(live);
    benchmark::ClobberMemory();
  }
}

static void BM_Sum(benchmark::State& state) {
  const auto count = static_cast<std::uint64_t>(state.range(0));
  std::vector<std::uint64_t> data(count);
  for (std::uint64_t i = 0; i < count; ++i) data[i] = i;
  const auto expected = count * (count - 1) / 2;
  if (sum(data) != expected) {
    state.SkipWithError("preflight checksum mismatch");
    return;
  }
  std::uint64_t observed = 0;
  for (auto _ : state) {
    benchmark::DoNotOptimize(data.data());
    observed = sum(data);
    benchmark::DoNotOptimize(observed);
    benchmark::ClobberMemory();
  }
  if (observed != expected) state.SkipWithError("measured checksum mismatch");
  state.SetItemsProcessed(state.iterations() * count);
  state.counters["checksum"] = static_cast<double>(observed);
}
BENCHMARK(BM_Empty);
BENCHMARK(BM_Sum)->Arg(1)->Arg(32)->Arg(1024);

int main(int argc, char** argv) {
  std::vector<std::uint64_t> input{1, 2, 3, 4};
  if (sum(input) != 10) {
    std::cerr << "preflight failed\n";
    return EXIT_FAILURE;
  }
  benchmark::Initialize(&argc, argv);
  if (benchmark::ReportUnrecognizedArguments(argc, argv)) return EXIT_FAILURE;
  benchmark::RunSpecifiedBenchmarks();
  benchmark::Shutdown();
}
