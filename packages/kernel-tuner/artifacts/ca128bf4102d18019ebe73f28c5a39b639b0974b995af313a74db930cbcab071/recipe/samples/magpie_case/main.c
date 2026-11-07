#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
void kernel(uint32_t*,int);
int main(int argc,char**argv) {
    int n=4096;
    uint32_t *out=calloc((size_t)n,sizeof(*out));
    int reps=(argc>1 && strcmp(argv[1],"--test")==0)?1:8;
    for(int r=0;r<reps;++r) kernel(out,n);
    uint64_t sum=0;
    for(int i=0;i<n;++i) {
        uint32_t ref=((uint32_t)(i*17+3)*33u)^(uint32_t)(i+7);
        if(out[i]!=ref) {fprintf(stderr,"incorrect output %d\n",i);free(out);return 1;}
        sum+=out[i];
    }
    printf("%llu\n",(unsigned long long)sum);free(out);return 0;
}
