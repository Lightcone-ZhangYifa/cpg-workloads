#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <libavutil/mem.h>
#include <libavutil/parseutils.h>
#include <libavutil/sha.h>
#include <libavutil/avutil.h>
#include <libavutil/version.h>

int main(void) {
    struct AVSHA *context = av_sha_alloc();
    unsigned char digest[32], color[4];
    char hex[65];
    if (context == NULL || av_sha_init(context, 256) != 0) return 1;
    av_sha_update(context, (const unsigned char *)"abc", 3);
    av_sha_final(context, digest);
    av_free(context);
    for (int i = 0; i < 32; i++) snprintf(hex + 2*i, 3, "%02x", digest[i]);
    if (strcmp(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad") != 0) return 2;
    int rejected = av_parse_color(color, "cpg-invalid-color", -1, NULL) < 0;
    int matched = avutil_version() == LIBAVUTIL_VERSION_INT;
    if (!rejected || !matched) return 3;
    printf("{\"sha256_abc\":\"%s\",\"invalid_color_rejected\":true,\"version_match\":true}\n", hex);
    return 0;
}
