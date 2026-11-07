#include <stdio.h>
extern int cpg_affine(int value);
int main(void)
{
    const int cases[] = {-17, -1, 0, 1, 21, 100000};
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        int actual = cpg_affine(cases[i]);
        if (actual != cases[i] * 3 + 5) return 10;
        printf("%d -> %d\n", cases[i], actual);
    }
    return 0;
}
