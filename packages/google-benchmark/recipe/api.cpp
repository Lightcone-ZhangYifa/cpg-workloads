#include <benchmark/benchmark.h>

static void BM_CPGSum(benchmark::State& state) {
    const int count = static_cast<int>(state.range(0));
    for (auto iteration : state) {
        (void)iteration;
        int sum = 0;
        for (int value = 0; value < count; ++value) {
            benchmark::DoNotOptimize(value);
            sum += value;
        }
        benchmark::DoNotOptimize(sum);
        benchmark::ClobberMemory();
    }
    state.SetItemsProcessed(state.iterations() * count);
    state.counters["argument"] = count;
}

BENCHMARK(BM_CPGSum)->Arg(64)->Iterations(256);

int main(int argc, char** argv) {
    benchmark::Initialize(&argc, argv);
    if (benchmark::ReportUnrecognizedArguments(argc, argv)) return 1;
    benchmark::RunSpecifiedBenchmarks();
    benchmark::Shutdown();
}
