#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdlib.h>
#include <time.h>

/* An explicitly checked, pure integer kernel. Timer excludes setup/oracle. */
double cpg_measure(int block, int unroll, int n, int repetitions, uint64_t *sum) {
    if (block <= 0 || unroll <= 0 || n <= 0 || repetitions <= 0 ||
        n % block || block % unroll || unroll > block) return -1.0;
    uint32_t *x = malloc((size_t)n * sizeof(*x));
    uint32_t *y = malloc((size_t)n * sizeof(*y));
    if (!x || !y) { free(x); free(y); return -2.0; }
    for (int i=0;i<n;++i) x[i] = (uint32_t)i * 17u + 3u;
    struct timespec a,b;
    clock_gettime(CLOCK_MONOTONIC, &a);
    for (int r=0;r<repetitions;++r) {
        for (int base=0;base<n;base+=block)
            for (int i=base;i<base+block;i+=unroll)
                for (int u=0;u<unroll;++u)
                    y[i+u] = (x[i+u] * 33u) ^ ((uint32_t)(i+u) + 7u);
        /* prevent entire repeated calls being optimized away */
        __asm__ __volatile__("" : : "g"(y) : "memory");
    }
    clock_gettime(CLOCK_MONOTONIC, &b);
    *sum = 0;
    for (int i=0;i<n;++i) {
        uint32_t ref = (((uint32_t)i * 17u + 3u) * 33u) ^ ((uint32_t)i + 7u);
        if (y[i] != ref) { free(x); free(y); return -3.0; }
        *sum += y[i];
    }
    free(x); free(y);
    return ((double)(b.tv_sec-a.tv_sec) + (b.tv_nsec-a.tv_nsec)*1e-9) / repetitions;
}
