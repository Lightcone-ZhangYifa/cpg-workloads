/* Independent public-C-API checks. The encoded stream is cross-decoded in Python. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "failed: %s at %d\n", #x, __LINE__); return 2; } } while (0)
int main(int argc, char **argv) {
    const size_t n = 65536;
    unsigned char *input = malloc(n), *output = malloc(n);
    uLong cap = compressBound((uLong)n);
    unsigned char *encoded = malloc(cap);
    REQUIRE(argc == 2 && input && output && encoded);
    for (size_t i = 0; i < n; ++i) input[i] = (unsigned char)(i * 17 + (i >> 3));
    REQUIRE(crc32(0L, (const Bytef *)"123456789", 9) == 0xcbf43926UL);
    REQUIRE(adler32(1L, (const Bytef *)"123456789", 9) == 0x091e01deUL);
    const int levels[] = {0, 1, 6, 9};
    uLongf used = 0;
    for (size_t k = 0; k < sizeof(levels) / sizeof(levels[0]); ++k) {
        used = cap;
        REQUIRE(compress2(encoded, &used, input, n, levels[k]) == Z_OK);
        uLongf actual = n;
        REQUIRE(uncompress(output, &actual, encoded, used) == Z_OK);
        REQUIRE(actual == n && memcmp(input, output, n) == 0);
        actual = n - 1;
        REQUIRE(uncompress(output, &actual, encoded, used) == Z_BUF_ERROR);
    }
    uLongf actual = n;
    REQUIRE(uncompress(output, &actual, encoded, used / 2) != Z_OK);
    FILE *file = fopen(argv[1], "wb");
    REQUIRE(file && fwrite(encoded, 1, used, file) == used && fclose(file) == 0);
    printf("{\"status\":\"passed\",\"library\":\"zlib\",\"version\":\"%s\",\"bytes\":%zu,\"roundtrip_levels\":4,\"known_checksums\":2}\n", zlibVersion(), n);
    free(encoded); free(output); free(input);
    return 0;
}
