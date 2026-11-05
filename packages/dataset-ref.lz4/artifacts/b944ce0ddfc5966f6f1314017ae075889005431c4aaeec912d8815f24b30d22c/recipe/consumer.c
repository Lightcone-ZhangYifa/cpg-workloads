#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <lz4.h>
#include <lz4hc.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "failed: %s at %d\n", #x, __LINE__); return 2; } } while (0)
int main(int argc, char **argv) {
    const int n = 65536;
    char *input = malloc(n), *output = malloc(n);
    int capacity = LZ4_compressBound(n);
    char *encoded = malloc((size_t)capacity);
    REQUIRE(argc == 2 && input && output && encoded);
    for (int i = 0; i < n; ++i) input[i] = (char)(i * 17 + (i >> 3));
    int used = LZ4_compress_default(input, encoded, n, capacity);
    REQUIRE(used > 0 && LZ4_decompress_safe(encoded, output, used, n) == n);
    REQUIRE(memcmp(input, output, n) == 0);
    REQUIRE(LZ4_decompress_safe(encoded, output, used, n - 1) < 0);
    REQUIRE(LZ4_decompress_safe(encoded, output, used / 2, n) != n);
    used = LZ4_compress_HC(input, encoded, n, capacity, 9);
    REQUIRE(used > 0 && LZ4_decompress_safe(encoded, output, used, n) == n);
    REQUIRE(memcmp(input, output, n) == 0);
    FILE *file = fopen(argv[1], "wb");
    REQUIRE(file && fwrite(encoded, 1, (size_t)used, file) == (size_t)used && fclose(file) == 0);
    printf("{\"status\":\"passed\",\"library\":\"lz4\",\"version\":\"%s\",\"bytes\":%d,\"default_and_hc\":true}\n", LZ4_versionString(), n);
    free(encoded); free(output); free(input);
    return 0;
}
