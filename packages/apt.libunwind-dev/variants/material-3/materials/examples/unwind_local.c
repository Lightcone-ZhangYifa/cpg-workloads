/* SPDX-License-Identifier: MIT
 * API: nongnu/libunwind, not LLVM's _Unwind_* runtime.
 */
#define UNW_LOCAL_ONLY
#include <libunwind.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static uintptr_t expected_return_ips[3];

__attribute__((noinline)) int cpg_example_leaf(void) {
    unw_context_t context;
    unw_cursor_t cursor;
    int seen_middle = 0, seen_outer = 0, seen_main = 0, count = 0;
    expected_return_ips[0] = (uintptr_t)__builtin_return_address(0);
    if (unw_getcontext(&context) < 0 || unw_init_local(&cursor, &context) < 0) return 10;
    int step;
    while ((step = unw_step(&cursor)) > 0 && count < 64) {
        char name[256];
        unw_word_t offset = 0, ip = 0;
        if (unw_get_reg(&cursor, UNW_REG_IP, &ip) < 0) return 11;
        int name_status = unw_get_proc_name(&cursor, name, sizeof(name), &offset);
        if (name_status == 0) {
            printf("frame=%d symbol=%s offset=%lu\n", count, name, (unsigned long)offset);
        } else {
            printf("frame=%d symbol_unavailable=%d\n", count, name_status);
        }
        /* Return addresses captured independently by GCC, before unwinding.
         * Symbol lookup is a separate, optional capability on restricted hosts.
         */
        if (count == 0 && (uintptr_t)ip == expected_return_ips[0]) seen_middle = 1;
        if (count == 1 && (uintptr_t)ip == expected_return_ips[1]) seen_outer = 1;
        if (count == 2 && (uintptr_t)ip == expected_return_ips[2]) seen_main = 1;
        ++count;
    }
    printf("frames=%d middle=%d outer=%d main=%d terminal=%d\n",
           count, seen_middle, seen_outer, seen_main, step);
    return (step == 0 && seen_middle && seen_outer && seen_main) ? 0 : 12;
}

__attribute__((noinline)) int cpg_example_middle(void) {
    expected_return_ips[1] = (uintptr_t)__builtin_return_address(0);
    int status = cpg_example_leaf();
    __asm__ volatile("" : "+r" (status));
    return status;
}

__attribute__((noinline)) int cpg_example_outer(void) {
    expected_return_ips[2] = (uintptr_t)__builtin_return_address(0);
    int status = cpg_example_middle();
    __asm__ volatile("" : "+r" (status));
    return status;
}

int main(void) {
    int status = cpg_example_outer();
    __asm__ volatile("" : "+r" (status));
    return status;
}
