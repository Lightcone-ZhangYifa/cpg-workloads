/* ABI fixture only: this is not Intel Advisor, VTune, or a timing collector. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <complex.h>
#define INTEL_NO_MACRO_BODY
#include "ittnotify.h"
static void named(const char *event, const char *name, size_t n, const char *wanted) {
    if (n != strlen(wanted) || memcmp(name, wanted, n)) abort();
    printf("advisor:%s:%.*s\n", event, (int)n, name);
}
static void value(const char *event, size_t n, size_t wanted) {
    if (n != wanted) abort();
    printf("advisor:%s:%zu\n", event, n);
}
static void memory(const char *event, const void *address, size_t n, unsigned *index) {
    const size_t sizes[] = {2,4,8,4,8,8,16};
    unsigned i = (*index)++;
    if (!address || i >= 7 || n != sizes[i]) abort();
    int valid = 0;
    switch (i) {
      case 0: valid = *(const int16_t *)address == 7; break;
      case 1: valid = *(const int32_t *)address == 7; break;
      case 2: valid = *(const int64_t *)address == 7; break;
      case 3: valid = *(const float *)address == 7; break;
      case 4: valid = *(const double *)address == 7; break;
      case 5: valid = crealf(*(const float complex *)address) == 7 && cimagf(*(const float complex *)address) == 2; break;
      case 6: valid = creal(*(const double complex *)address) == 7 && cimag(*(const double complex *)address) == 2; break;
    }
    if (!valid) abort();
    printf("advisor:%s:%u:%zu\n", event, i, n);
}
void __itt_model_site_beginAL(const char *s, size_t n) { named("site_begin", s, n, "cpg-site"); }
void __itt_model_task_beginAL(const char *s, size_t n) { named("task_begin", s, n, "cpg-task"); }
void __itt_model_iteration_taskAL(const char *s, size_t n) { named("iteration_task", s, n, "cpg-iteration"); }
void __itt_model_site_end_2(void) { puts("advisor:site_end"); }
void __itt_model_task_end_2(void) { puts("advisor:task_end"); }
void __itt_model_lock_acquire_2(void *n) { value("lock_acquire", (uintptr_t)n, 17); }
void __itt_model_lock_release_2(void *n) { value("lock_release", (uintptr_t)n, 17); }
void __itt_model_disable_push(__itt_model_disable n) { if (n != 0 && n != 1) abort(); printf("advisor:disable_push:%d\n", n); }
void __itt_model_disable_pop(void) { puts("advisor:disable_pop"); }
void __itt_model_induction_uses(void *a, size_t n) { static unsigned i; memory("induction", a, n, &i); }
void __itt_model_reduction_uses(void *a, size_t n) { static unsigned i; memory("reduction", a, n, &i); }
void __itt_model_observe_uses(void *a, size_t n) { static unsigned i; memory("observe", a, n, &i); }
void __itt_model_clear_uses(void *a, size_t n) { static unsigned i; memory("clear", a, n, &i); }
void __itt_model_aggregate_task(size_t n) { value("aggregate", n, 9); }
