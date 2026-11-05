#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <turbojpeg.h>

int main(void) {
  const int width = 64, height = 48;
  unsigned char input[64 * 48 * 3], output[64 * 48 * 3];
  unsigned char *jpeg = NULL;
  unsigned long size = 0;
  int w = 0, h = 0, subsamp = -1, space = -1;
  tjhandle encoder = tjInitCompress(), decoder = tjInitDecompress();
  if (!encoder || !decoder) return 10;
  for (int i = 0; i < width * height; ++i) {
    input[3*i] = 32; input[3*i+1] = 96; input[3*i+2] = 192;
  }
  if (tjCompress2(encoder, input, width, 0, height, TJPF_RGB, &jpeg, &size,
                  TJSAMP_444, 100, TJFLAG_ACCURATEDCT) || !jpeg || size < 32) return 11;
  if (tjDecompressHeader3(decoder, jpeg, size, &w, &h, &subsamp, &space) ||
      w != width || h != height || subsamp != TJSAMP_444 || space != TJCS_YCbCr) return 12;
  if (tjDecompress2(decoder, jpeg, size, output, width, 0, height, TJPF_RGB, TJFLAG_ACCURATEDCT)) return 13;
  int max_error = 0;
  for (int i = 0; i < width * height * 3; ++i) {
    int error = abs((int)input[i] - (int)output[i]);
    if (error > max_error) max_error = error;
    if (error > 3) return 14;
  }
  const unsigned char invalid[] = "This is not a JPEG image";
  if (tjDecompressHeader3(decoder, invalid, sizeof(invalid), &w, &h, &subsamp, &space) == 0) return 15;
  if (!tjGetErrorStr2(decoder) || strlen(tjGetErrorStr2(decoder)) == 0) return 16;
  printf("{\"width\":64,\"height\":48,\"jpeg_bytes\":%lu,\"max_error\":%d,\"invalid_jpeg_rejected\":true}\n", size, max_error);
  tjFree(jpeg);
  if (tjDestroy(encoder) || tjDestroy(decoder)) return 17;
  return 0;
}
