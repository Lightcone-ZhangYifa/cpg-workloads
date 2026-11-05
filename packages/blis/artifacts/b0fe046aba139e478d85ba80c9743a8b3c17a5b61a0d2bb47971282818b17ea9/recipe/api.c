#include <blis.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int check_gemm(int transpose_a, int transpose_b, int m, int n, int k) {
  const int lda = (transpose_a ? m : k) + 3;
  const int ldb = (transpose_b ? k : n) + 5;
  const int ldc = n + 7;
  double a[4096], b[4096], c[4096], original[4096];
  for (int i = 0; i < 4096; ++i) { a[i] = ((i*7)%31-15)/8.0; b[i] = ((i*11)%29-14)/16.0; c[i] = original[i] = ((i*13)%19-9)/4.0; }
  cblas_dgemm(CblasRowMajor, transpose_a ? CblasTrans : CblasNoTrans, transpose_b ? CblasTrans : CblasNoTrans,
              m,n,k,1.25,a,lda,b,ldb,-0.5,c,ldc);
  for (int i=0; i<m; ++i) for (int j=0; j<ldc; ++j) {
    long double reference = original[i*ldc+j];
    if (j<n) {
      long double sum=0;
      for (int p=0; p<k; ++p) sum += (long double)a[transpose_a ? p*lda+i : i*lda+p] * b[transpose_b ? j*ldb+p : p*ldb+j];
      reference=1.25L*sum-0.5L*reference;
    }
    if (fabsl((long double)c[i*ldc+j]-reference)>1e-10L*(1+fabsl(reference))) return 1;
  }
  return 0;
}

int main(int argc, char** argv) {
  bli_init();
  if (strcmp(bli_info_get_version_str(),"2.1") || !bli_info_get_enable_cblas() || !bli_info_get_enable_pthreads()) return 10;
  if (argc == 2 && !strcmp(argv[1],"--invalid")) {
    double a[4]={1,2,3,4},b[4]={1,2,3,4},c[4]={0};
    cblas_dgemm((enum CBLAS_ORDER)999,CblasNoTrans,CblasNoTrans,2,2,2,1,a,2,b,2,0,c,2);
    return 42;
  }
  int cases=0;
  const int sizes_m[]={1,7,17},sizes_n[]={1,5,19},sizes_k[]={0,3,13};
  for (int threads=1;threads<=2;++threads) {
    bli_thread_set_num_threads(threads);
    if (bli_thread_get_num_threads()!=threads) return 11;
    for(int ta=0;ta<2;++ta) for(int tb=0;tb<2;++tb)
      for(int im=0;im<3;++im) for(int in=0;in<3;++in) for(int ik=0;ik<3;++ik) {
        if(check_gemm(ta,tb,sizes_m[im],sizes_n[in],sizes_k[ik]))return 12;
        ++cases;
      }
  }
  double x[]={1,2,3,4,5,6},y[]={6,5,4,3,2,1};
  if (cblas_ddot(3,x,2,y,2)!=28.0) return 13;
  cblas_daxpy(3,2.0,x,2,y,2);
  if(y[0]!=8||y[2]!=10||y[4]!=12||y[1]!=5||y[3]!=3||y[5]!=1)return 14;
  double native_a[]={1,2,3,4,5,6},native_b[]={7,8,9,10,11,12},native_c[4]={0};
  double alpha=1,beta=0;
  bli_dgemm(BLIS_NO_TRANSPOSE,BLIS_NO_TRANSPOSE,2,2,3,&alpha,native_a,3,1,native_b,2,1,&beta,native_c,2,1);
  if(native_c[0]!=58||native_c[1]!=64||native_c[2]!=139||native_c[3]!=154)return 15;
  printf("{\"version\":\"2.1\",\"dgemm_cases\":%d,\"thread_settings\":[1,2],\"strided_blas1\":true,\"native_typed_api\":true}\n",cases);
  bli_finalize();
  return 0;
}
