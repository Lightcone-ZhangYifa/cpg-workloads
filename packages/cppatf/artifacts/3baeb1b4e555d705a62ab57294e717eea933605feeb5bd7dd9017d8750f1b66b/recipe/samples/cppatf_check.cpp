#include <cppatf.hpp>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <set>
#include <stdexcept>
extern "C" double cpg_measure(int,int,int,int,uint64_t*);
int main() {
    const int n=131072;
    auto block=atf::tuning_parameter("block",atf::set<int>({16,32,64,128,192}),[&](int b){return n%b==0;});
    auto unroll=atf::tuning_parameter("unroll",atf::set<int>({1,2,3,4,8}),[&](int u){return int(block)%u==0 && u<=int(block);});
    std::ofstream trials("cppatf-trials.jsonl");
    std::set<std::pair<int,int>> seen;
    int evaluations=0;
    auto cost=[&](atf::configuration& c)->double {
        int b=c["block"].value(),u=c["unroll"].value();
        if(n%b || b%u || u>b) throw std::runtime_error("illegal configuration reached kernel");
        uint64_t checksum=0;
        double value=cpg_measure(b,u,n,60,&checksum);
        if(!(value>0) || !std::isfinite(value)) throw std::runtime_error("incorrect kernel");
        seen.emplace(b,u); ++evaluations;
        trials << std::setprecision(17) << "{\"block\":"<<b<<",\"unroll\":"<<u<<",\"seconds\":"<<value<<",\"checksum\":"<<checksum<<",\"correct\":true}\n";
        return value;
    };
    auto status=atf::tuner().tuning_parameters(block,unroll).search_technique(atf::exhaustive()).silent(true).log_file("cppatf-upstream.csv").tune(cost,atf::evaluations(16));
    if(evaluations!=16 || seen.size()!=16 || status.number_of_invalid_configs()!=0) return 2;
    auto best=status.best_configuration();
    uint64_t checksum=0; int b=best["block"].value(),u=best["unroll"].value();
    double replay=cpg_measure(b,u,n,60,&checksum);
    uint64_t bad_sum=0;
    if(cpg_measure(192,3,n,1,&bad_sum)!=-1.0 || !(replay>0)) return 3;
    std::ofstream out("cppatf-result.json");
    out << std::setprecision(17)<<"{\"status\":\"pass\",\"backend\":\"native_cpu\",\"evaluated\":16,\"unique_configs\":16,\"constraint_rejected_count\":9,\"invalid_executed\":0,\"budget\":16,\"repetitions\":60,\"time_unit\":\"seconds_per_repetition\",\"best\":{\"block\":"<<b<<",\"unroll\":"<<u<<"},\"best_seconds\":"<<status.min_cost()<<",\"replay_seconds\":"<<replay<<",\"checksum\":"<<checksum<<",\"correctness\":true,\"negative_invalid_config_rejected\":true}\n";
}
