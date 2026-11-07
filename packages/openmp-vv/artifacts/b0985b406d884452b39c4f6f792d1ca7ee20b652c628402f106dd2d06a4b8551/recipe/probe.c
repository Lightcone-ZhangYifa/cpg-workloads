#include <omp.h>
#include <stdio.h>
#include <string.h>
int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--devices") == 0) {
    printf("{\"openmp_macro\":%d,\"num_devices\":%d}\n", _OPENMP, omp_get_num_devices());
    return 0;
  }
  if (argc != 1) return 2;
  int initial=-1;
  #pragma omp target map(from:initial)
  { initial=omp_is_initial_device(); }
  printf("{\"openmp_macro\":%d,\"num_devices\":%d,\"target_initial_device\":%d}\n",_OPENMP,omp_get_num_devices(),initial);
  return 0;
}
