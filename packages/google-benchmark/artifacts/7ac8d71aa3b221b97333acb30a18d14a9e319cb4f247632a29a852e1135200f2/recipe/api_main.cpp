#include <benchmark/benchmark.h>

static void BM_CPGDefaultMain(benchmark::State& state) {
    for (auto iteration : state) {
        (void)iteration;
        int value = 42;
        benchmark::DoNotOptimize(value);
    }
}

BENCHMARK(BM_CPGDefaultMain)->Iterations(256);
