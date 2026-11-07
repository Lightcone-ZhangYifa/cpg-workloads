#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>
#ifndef TILE
#define TILE 8
#endif
#ifndef REFERENCE
#define REFERENCE 0
#endif
static uint64_t ns(void) { struct timespec t; if (clock_gettime(CLOCK_MONOTONIC_RAW,&t)) exit(3); return (uint64_t)t.tv_sec*1000000000ull+t.tv_nsec; }
int main(int argc,char **argv) {
 if(argc!=4) return 2;
 int n=atoi(argv[1]), rounds=atoi(argv[2]); unsigned seed=(unsigned)strtoul(argv[3],0,10);
 if(n<1||n>256||rounds<1||rounds>2000||TILE<1) return 2;
 uint32_t *a=calloc((size_t)n*n,sizeof(*a)),*b=calloc((size_t)n*n,sizeof(*b)),*c=calloc((size_t)n*n,sizeof(*c));
 if(!a||!b||!c) return 3;
 for(int i=0;i<n*n;i++) {a[i]=(uint32_t)((i*17u+seed*13u)%251u);b[i]=(uint32_t)((i*29u+seed*7u)%127u);}
#ifdef FAULT_TIMEOUT
 sleep(10);
#endif
 uint64_t start=ns(), checksum=1469598103934665603ull;
 for(int r=0;r<rounds;r++) {
  a[(unsigned)r%(unsigned)(n*n)]+=(uint32_t)(r+1);
  for(int i=0;i<n*n;i++) c[i]=0;
#if REFERENCE
  for(int i=0;i<n;i++) for(int j=0;j<n;j++) for(int k=0;k<n;k++) c[i*n+j]+=a[i*n+k]*b[k*n+j];
#else
  for(int ii=0;ii<n;ii+=TILE) for(int kk=0;kk<n;kk+=TILE) for(int jj=0;jj<n;jj+=TILE)
   for(int i=ii;i<n&&i<ii+TILE;i++) for(int k=kk;k<n&&k<kk+TILE;k++) for(int j=jj;j<n&&j<jj+TILE;j++) c[i*n+j]+=a[i*n+k]*b[k*n+j];
#endif
#ifdef FAULT_WRONG
  c[0]^=1;
#endif
  for(int i=0;i<n*n;i++) checksum=(checksum ^ c[i])*1099511628211ull;
 }
 uint64_t elapsed=ns()-start;
 printf("%llu %llu\n",(unsigned long long)elapsed,(unsigned long long)checksum);
 free(a);free(b);free(c);return 0;
}
