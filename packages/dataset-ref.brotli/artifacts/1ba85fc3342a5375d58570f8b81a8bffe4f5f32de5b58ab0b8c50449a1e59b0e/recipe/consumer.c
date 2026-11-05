#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <brotli/encode.h>
#include <brotli/decode.h>
#define REQUIRE(x) do { if (!(x)) { fprintf(stderr, "failed: %s at %d\n", #x, __LINE__); return 2; } } while (0)
int main(int argc, char **argv) {
    const size_t n = 65536;
    unsigned char *input = malloc(n), *output = malloc(n);
    size_t capacity = BrotliEncoderMaxCompressedSize(n);
    unsigned char *encoded = malloc(capacity);
    REQUIRE(argc == 2 && input && output && encoded);
    for (size_t i = 0; i < n; ++i) input[i] = (unsigned char)(i * 17 + (i >> 3));
    size_t used = capacity;
    REQUIRE(BrotliEncoderCompress(5, 22, BROTLI_MODE_GENERIC, n, input, &used, encoded) == BROTLI_TRUE);
    size_t produced = n;
    REQUIRE(BrotliDecoderDecompress(used, encoded, &produced, output) == BROTLI_DECODER_RESULT_SUCCESS);
    REQUIRE(produced == n && memcmp(input, output, n) == 0);
    produced = n - 1;
    REQUIRE(BrotliDecoderDecompress(used, encoded, &produced, output) != BROTLI_DECODER_RESULT_SUCCESS);
    produced = n;
    REQUIRE(BrotliDecoderDecompress(used / 2, encoded, &produced, output) != BROTLI_DECODER_RESULT_SUCCESS);
    FILE *file = fopen(argv[1], "wb");
    REQUIRE(file && fwrite(encoded, 1, used, file) == used && fclose(file) == 0);
    printf("{\"status\":\"passed\",\"library\":\"brotli\",\"encoder_version\":%u,\"decoder_version\":%u,\"bytes\":%zu}\n", BrotliEncoderVersion(), BrotliDecoderVersion(), n);
    free(encoded); free(output); free(input);
    return 0;
}
