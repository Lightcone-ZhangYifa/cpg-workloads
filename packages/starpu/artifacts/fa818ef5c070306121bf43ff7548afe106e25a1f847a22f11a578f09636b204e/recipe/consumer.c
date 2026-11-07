#ifndef _GNU_SOURCE
#define _GNU_SOURCE 1
#endif
#include <starpu.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <sched.h>

static int mutate_bias = 0;
// Keep task A unfinished until the host has submitted task B.
// This makes the RW dependency pending during B submission without a host wait.
static atomic_int second_submitted = 0;

static void scale(void *buffers[],void *arg) {
  (void)arg;
  while (!atomic_load_explicit(&second_submitted, memory_order_acquire))
    sched_yield();
  long long *v=(long long*)STARPU_VECTOR_GET_PTR(buffers[0]);
  unsigned n=STARPU_VECTOR_GET_NX(buffers[0]);
  for(unsigned i=0;i<n;++i)v[i]*=3;
}
static void bias(void *buffers[],void *arg) {
  (void)arg;
  long long *v=(long long*)STARPU_VECTOR_GET_PTR(buffers[0]);
  unsigned n=STARPU_VECTOR_GET_NX(buffers[0]);
  for(unsigned i=0;i<n;++i)v[i]+=11+mutate_bias;
}
static struct starpu_codelet first={.where=STARPU_CPU,.cpu_funcs={scale},.nbuffers=1,.modes={STARPU_RW},.name="scale"};
static struct starpu_codelet second={.where=STARPU_CPU,.cpu_funcs={bias},.nbuffers=1,.modes={STARPU_RW},.name="bias"};
int main(int argc,char**argv) {
  if(argc!=4)return 2;
  int cpus=atoi(argv[1]),n=atoi(argv[2]),seed=atoi(argv[3]);
  if(cpus<1||cpus>4||n<1||n>4096||seed<0||seed>65535)return 2;
  mutate_bias=getenv("CPG_TEST_MUTATE")!=NULL;
  struct starpu_conf conf;starpu_conf_init(&conf);conf.ncpus=cpus;conf.ncuda=0;conf.nopencl=0;
  int rc=starpu_init(&conf);if(rc){fprintf(stderr,"starpu_init=%d\n",rc);return 3;}
  long long *v=calloc((size_t)n,sizeof(*v));if(!v)return 4;
  for(int i=0;i<n;++i)v[i]=seed+i;
  starpu_data_handle_t handle;
  starpu_vector_data_register(&handle,STARPU_MAIN_RAM,(uintptr_t)v,n,sizeof(*v));
  struct starpu_task *a=starpu_task_create();a->cl=&first;a->handles[0]=handle;
  rc=starpu_task_submit(a);if(rc)return 5;
  // Both tasks access the same handle RW. StarPU orders them without a host wait.
  struct starpu_task *b=starpu_task_create();b->cl=&second;b->handles[0]=handle;
  rc=starpu_task_submit(b);if(rc)return 6;
  atomic_store_explicit(&second_submitted, 1, memory_order_release);
  rc=starpu_task_wait_for_all();if(rc)return 7;
  starpu_data_unregister(handle);
  printf("{\"cpus\":%d,\"n\":%d,\"seed\":%d,\"cpu_workers\":%u,\"result\":[",cpus,n,seed,starpu_cpu_worker_get_count());
  for(int i=0;i<n;++i){if(i)printf(",");printf("%lld",v[i]);}
  printf("]}\n");free(v);starpu_shutdown();return 0;
}
