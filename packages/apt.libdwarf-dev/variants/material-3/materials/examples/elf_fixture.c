/* SPDX-License-Identifier: MIT
 * A two-translation-unit ELF/DWARF fixture; returns 0 only for the expected result.
 */
#include <stdio.h>
extern int external_transform(int);
int observable_value = 7;

__attribute__((noinline)) int cpg_example_entry(int value) {
    int intermediate = external_transform(value);
    return intermediate + observable_value;
}

int main(void) {
    int result = cpg_example_entry(5);
    printf("cpg_example-result=%d\n", result);
    return result == 23 ? 0 : 1;
}
