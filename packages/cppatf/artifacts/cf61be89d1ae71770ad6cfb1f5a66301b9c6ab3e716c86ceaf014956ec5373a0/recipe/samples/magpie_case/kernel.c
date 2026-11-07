#include <stdint.h>
void kernel(uint32_t *out, int n) {
    for (int i=0;i<n;++i) {
        out[i] = (uint32_t)(i * 17 + 3);
        out[i] = out[i] * 33u;
        out[i] = out[i] ^ (uint32_t)(i + 7);
        volatile uint32_t noise=0;
        for (int k=0;k<500;++k) noise += (uint32_t)k;
    }
}
