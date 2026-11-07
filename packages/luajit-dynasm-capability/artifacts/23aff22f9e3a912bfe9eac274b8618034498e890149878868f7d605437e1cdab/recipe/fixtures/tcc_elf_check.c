#include <stdio.h>
int main(void) {int sum=0;for(int i=0;i<1000;i++)sum+=i;printf("TCC_ELF_PASS sum=%d\n",sum);return sum==499500?0:1;}
