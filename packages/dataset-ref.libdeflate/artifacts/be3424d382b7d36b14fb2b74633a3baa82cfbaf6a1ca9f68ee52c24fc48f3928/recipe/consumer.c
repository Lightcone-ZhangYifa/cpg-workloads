#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libdeflate.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "failed: %s at %d\n", #x, __LINE__); return 2; } } while (0)
int main(int argc, char **argv) {
    const size_t n = 65536;
    unsigned char *input = malloc(n), *output = malloc(n);
    struct libdeflate_compressor *compressor = libdeflate_alloc_compressor(12);
    struct libdeflate_decompressor *decompressor = libdeflate_alloc_decompressor();
    REQUIRE(argc == 2 && input && output && compressor && decompressor);
    for (size_t i = 0; i < n; ++i) input[i] = (unsigned char)(i * 17 + (i >> 3));
    size_t capacity = libdeflate_zlib_compress_bound(compressor, n);
    unsigned char *encoded = malloc(capacity);
    REQUIRE(encoded);
    size_t used = libdeflate_zlib_compress(compressor, input, n, encoded, capacity);
    REQUIRE(used > 0);
    size_t consumed = 0, produced = 0;
    REQUIRE(libdeflate_zlib_decompress_ex(decompressor, encoded, used, output, n, &consumed, &produced) == LIBDEFLATE_SUCCESS);
    REQUIRE(consumed == used && produced == n && memcmp(output, input, n) == 0);
    REQUIRE(libdeflate_zlib_decompress(decompressor, encoded, used, output, n - 1, &produced) == LIBDEFLATE_INSUFFICIENT_SPACE);
    REQUIRE(libdeflate_zlib_decompress(decompressor, encoded, used / 2, output, n, &produced) != LIBDEFLATE_SUCCESS);
    REQUIRE(libdeflate_crc32(0, "123456789", 9) == 0xcbf43926UL);
    REQUIRE(libdeflate_adler32(1, "123456789", 9) == 0x091e01deUL);
    FILE *file = fopen(argv[1], "wb");
    REQUIRE(file && fwrite(encoded, 1, used, file) == used && fclose(file) == 0);
    printf("{\"status\":\"passed\",\"library\":\"libdeflate\",\"bytes\":%zu,\"truncation_and_short_buffer\":true,\"known_checksums\":2}\n", n);
    free(encoded); free(output); free(input);
    libdeflate_free_decompressor(decompressor); libdeflate_free_compressor(compressor);
    return 0;
}
