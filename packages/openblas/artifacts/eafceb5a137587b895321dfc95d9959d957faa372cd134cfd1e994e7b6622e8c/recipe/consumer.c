#include <cblas.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int errors, error_info;
static char error_routine[32];

static void require(int value, const char *message) {
    if (!value) { fprintf(stderr, "FAIL: %s\n", message); exit(1); }
}
static void near(double actual, double expected) {
    require(isfinite(actual) && fabs(actual - expected) < 1e-5, "independent numerical oracle");
}
static void on_error(const char *name, const blasint *info, size_t length) {
    ++errors; error_info = *info;
    require(length < sizeof(error_routine), "bounded error routine name");
    memcpy(error_routine, name, length); error_routine[length] = 0;
}
static void profile(void) {
    const char *s = openblas_get_config();
    require(strstr(s, "OpenBLAS 0.3.34") != NULL, "version");
    require(strstr(s, "NO_LAPACK") && strstr(s, "NO_LAPACKE"), "declared BLAS-only profile");
    require(!strstr(s, "USE64BITINT") && !strstr(s, "DYNAMIC_ARCH"), "fixed LP64 architecture");
    require(sizeof(blasint) == 4 && openblas_get_parallel() == 0, "LP64 sequential ABI");
    require(openblas_get_num_threads() == 1, "single runtime worker");
    require(strcmp(openblas_get_corename(), "NEHALEM") == 0, "fixed NEHALEM kernels");
}
static void self_test(void) {
    double x[] = {1,2,3}, y[] = {4,5,6};
    near(cblas_ddot(3,x,1,y,1),32);
    cblas_daxpy(3,2,x,1,y,1); near(y[0],6); near(y[1],9); near(y[2],12);
    double a[] = {1,2,3,4,5,6}, v[] = {1,-1,2}, result[] = {0,0};
    cblas_dgemv(CblasRowMajor,CblasNoTrans,2,3,1,a,3,v,1,0,result,1);
    near(result[0],5); near(result[1],11);
    double b[] = {7,8,9,10,11,12}, product[] = {0,0,0,0};
    cblas_dgemm(CblasRowMajor,CblasNoTrans,CblasNoTrans,2,2,3,1,a,3,b,2,0,product,2);
    near(product[0],58); near(product[1],64); near(product[2],139); near(product[3],154);
    double upper[] = {2,1,0,3}, rhs[] = {5,6};
    cblas_dtrsv(CblasRowMajor,CblasUpper,CblasNoTrans,CblasNonUnit,2,upper,2,rhs,1);
    near(rhs[0],1.5); near(rhs[1],2);
    float sx[] = {1,99,2,99,3}, sy[] = {4,5,6};
    near(cblas_sdot(3,sx,2,sy,1),32);
    double za[] = {1,2}, zb[] = {3,-4}, zc[] = {0,0}, alpha[] = {1,0}, beta[] = {0,0};
    cblas_zgemm(CblasColMajor,CblasNoTrans,CblasNoTrans,1,1,1,alpha,za,1,zb,1,beta,zc,1);
    near(zc[0],11); near(zc[1],2);
    float cx[] = {1,2,3,-1}, cy[] = {2,1,-1,4}, cz[] = {0,0};
    cblas_cdotc_sub(2,cx,1,cy,1,cz); near(cz[0],-3); near(cz[1],8);

    double guard[] = {9,9,9,9};
    openblas_xerbla_handler previous = openblas_set_xerbla(on_error);
    cblas_dgemm(CblasColMajor,CblasNoTrans,CblasNoTrans,-1,2,2,1,upper,2,upper,2,0,guard,2);
    require(errors==1 && error_info==3 && strncmp(error_routine,"DGEMM ",6)==0,"negative dimension rejected");
    cblas_dgemm(CblasColMajor,(enum CBLAS_TRANSPOSE)999,CblasNoTrans,2,2,2,1,upper,2,upper,2,0,guard,2);
    require(errors==2 && error_info==1 && strncmp(error_routine,"DGEMM ",6)==0,"invalid transpose rejected");
    cblas_dgemm(CblasColMajor,CblasNoTrans,CblasNoTrans,2,2,2,1,upper,1,upper,2,0,guard,2);
    require(errors==3 && error_info==8 && strncmp(error_routine,"DGEMM ",6)==0,"invalid leading dimension rejected");
    for (int i=0;i<4;++i) near(guard[i],9);
    float ca[] = {9,9,9,9,9,9,9,9}, calpha[] = {1,0};
    cblas_cgerc(CblasColMajor,2,2,calpha,cx,1,cy,1,ca,1);
    require(errors==4 && error_info==9 && strncmp(error_routine,"CGERC ",6)==0,"complex gerc invalid leading dimension rejected");
    for (int i=0;i<8;++i) near(ca[i],9);
    double zx[] = {1,2,3,-1}, zy[] = {2,1,-1,4}, zguard[] = {9,9,9,9,9,9,9,9};
    cblas_zgerc(CblasColMajor,2,2,alpha,zx,1,zy,1,zguard,1);
    require(errors==5 && error_info==9 && strncmp(error_routine,"ZGERC ",6)==0,"double-complex gerc invalid leading dimension rejected");
    for (int i=0;i<8;++i) near(zguard[i],9);
    require(openblas_set_xerbla(previous)==on_error,"error handler restored");
    puts("{\"status\":\"passed\",\"numerical_cases\":8,\"invalid_parameters_rejected\":5,\"error_parameter_indices\":[3,1,8,9,9],\"version\":\"0.3.34\"}");
}
int main(int argc, char **argv) {
    if (argc!=2 || (strcmp(argv[1],"--info") && strcmp(argv[1],"--self-test"))) {
        fputs("usage: openblas-cpg-probe --info|--self-test\n",stderr); return 2;
    }
    profile();
    if (!strcmp(argv[1],"--self-test")) self_test();
    else printf("{\"version\":\"0.3.34\",\"integer_bits\":%zu,\"runtime_threads\":%d,\"parallel_backend\":%d,\"core\":\"%s\",\"config\":\"%s\"}\n",
        sizeof(blasint)*8,openblas_get_num_threads(),openblas_get_parallel(),openblas_get_corename(),openblas_get_config());
    return 0;
}
