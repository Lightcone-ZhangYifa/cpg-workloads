#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#ifndef CPG_SERIAL
#include <cilk/cilk_api.h>
#include <stdatomic.h>
static _Atomic uint64_t worker_mask;
static void sum_identity(void *view) { *(int64_t *)view = 0; }
static void sum_reduce(void *left, void *right) {
  *(int64_t *)left += *(int64_t *)right;
}
#define CPG_LOOP cilk_for
#define CPG_SUM int64_t cilk_reducer(sum_identity, sum_reduce)
#else
#define CPG_LOOP for
#define CPG_SUM int64_t
#endif

static int64_t value(uint64_t index, uint64_t seed) {
  return (int64_t)((index * 17u + seed * 29u) % 257u) - 128;
}

int main(int argc, char **argv) {
  if (argc != 3) return 2;
  char *end = NULL;
  errno = 0;
  uint64_t n = strtoull(argv[1], &end, 10);
  if (errno || !end || *end || argv[1][0] == '-' || n > 1000000) return 2;
  errno = 0;
  uint64_t seed = strtoull(argv[2], &end, 10);
  if (errno || !end || *end || argv[2][0] == '-' || seed > 1000000) return 2;
  CPG_SUM sum = 0;
  CPG_LOOP (uint64_t i = 0; i < n; ++i) {
    sum += value(i, seed);
#ifndef CPG_SERIAL
    int worker = __cilkrts_get_worker_number();
    if (worker >= 0 && worker < 64)
      atomic_fetch_or_explicit(&worker_mask, UINT64_C(1) << worker,
                               memory_order_relaxed);
#endif
  }
  int64_t result = sum;
#ifdef CPG_BAD_RESULT
  result += 1;
#endif
#ifndef CPG_SERIAL
  int workers = __cilkrts_get_nworkers();
  uint64_t mask = atomic_load_explicit(&worker_mask, memory_order_relaxed);
#else
  int workers = 1;
  uint64_t mask = n ? 1 : 0;
#endif
  printf("{\"n\":%" PRIu64 ",\"seed\":%" PRIu64 ",\"sum\":%" PRId64
         ",\"workers\":%d,\"worker_mask\":%" PRIu64 "}\n",
         n, seed, result, workers, mask);
  return 0;
}
