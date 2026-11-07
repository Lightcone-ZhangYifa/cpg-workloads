#include "legion.h"
#include <cstdio>
#include <cstdint>
#include <cstdlib>
using namespace Legion;
enum { TOP=1, INITIALIZE=2, TRANSFORM=3, VALUE=10 };
struct Input { int n; long long seed; };

void initialize(const Task* task, const std::vector<PhysicalRegion>& regions, Context ctx, Runtime* rt) {
  const Input in = *static_cast<const Input*>(task->args);
  const FieldAccessor<WRITE_DISCARD,long long,1> out(regions[0], VALUE);
  const Rect<1> bounds = rt->get_index_space_domain(ctx, task->regions[0].region.get_index_space());
  for(PointInRectIterator<1> it(bounds); it(); it++) out[*it] = in.seed + (*it)[0];
}
long long transform(const Task* task, const std::vector<PhysicalRegion>& regions, Context ctx, Runtime* rt) {
  const FieldAccessor<READ_WRITE,long long,1> values(regions[0], VALUE);
  const Rect<1> bounds = rt->get_index_space_domain(ctx, task->regions[0].region.get_index_space());
  long long sum = 0;
  const long long bias = std::getenv("CPG_TEST_MUTATE") ? 12 : 11;
  for(PointInRectIterator<1> it(bounds); it(); it++) {
    values[*it] = 3*values[*it]+bias;
    sum += values[*it];
  }
  return sum;
}
void top(const Task*, const std::vector<PhysicalRegion>&, Context ctx, Runtime* rt) {
  for(int n : {1,17,257}) for(long long seed : {1LL,13LL}) {
    Input in{n,seed};
    auto is = rt->create_index_space(ctx, Rect<1>(0,n-1));
    auto fs = rt->create_field_space(ctx);
    rt->create_field_allocator(ctx,fs).allocate_field(sizeof(long long),VALUE);
    auto lr = rt->create_logical_region(ctx,is,fs);
    TaskLauncher first(INITIALIZE,TaskArgument(&in,sizeof(in)));
    first.add_region_requirement(RegionRequirement(lr,WRITE_DISCARD,EXCLUSIVE,lr));
    first.region_requirements[0].add_field(VALUE);
    rt->execute_task(ctx,first);
    // No host wait between submissions: logical-region privileges induce dependence.
    TaskLauncher second(TRANSFORM,TaskArgument(nullptr,0));
    second.add_region_requirement(RegionRequirement(lr,READ_WRITE,EXCLUSIVE,lr));
    second.region_requirements[0].add_field(VALUE);
    long long result = rt->execute_task(ctx,second).get_result<long long>();
    std::printf("LEGION_RESULT {\"n\":%d,\"seed\":%lld,\"sum\":%lld}\n",n,seed,result);
    rt->destroy_logical_region(ctx,lr);
    rt->destroy_field_space(ctx,fs);
    rt->destroy_index_space(ctx,is);
  }
}
int main(int argc,char** argv) {
  Runtime::set_top_level_task_id(TOP);
  { TaskVariantRegistrar r(TOP,"top"); r.add_constraint(ProcessorConstraint(Processor::LOC_PROC));
    Runtime::preregister_task_variant<top>(r,"top"); }
  { TaskVariantRegistrar r(INITIALIZE,"initialize"); r.add_constraint(ProcessorConstraint(Processor::LOC_PROC)); r.set_leaf();
    Runtime::preregister_task_variant<initialize>(r,"initialize"); }
  { TaskVariantRegistrar r(TRANSFORM,"transform"); r.add_constraint(ProcessorConstraint(Processor::LOC_PROC)); r.set_leaf();
    Runtime::preregister_task_variant<long long,transform>(r,"transform"); }
  return Runtime::start(argc,argv);
}
