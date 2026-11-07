#include <taskflow/taskflow.hpp>
#include <atomic>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void vector_json(const std::vector<std::int64_t>& v) {
  std::cout << '[';
  for(size_t i=0; i<v.size(); ++i) { if(i) std::cout << ','; std::cout << v[i]; }
  std::cout << ']';
}

int main(int argc, char** argv) {
  try {
    if(argc != 3 && argc != 4) throw std::runtime_error("usage: consumer WORKERS SEED [mutate]");
    const int workers = std::stoi(argv[1]);
    const std::int64_t seed = std::stoll(argv[2]);
    const bool mutate = argc == 4 && std::string(argv[3]) == "mutate";
    if(workers < 1 || workers > 32 || seed < 0 || seed > 65535) throw std::runtime_error("input outside bounded test domain");
    tf::Executor executor(workers);
    for(size_t n : {size_t(0), size_t(1), size_t(17), size_t(257)}) {
      tf::Taskflow graph("dependency_diamond");
      std::vector<std::int64_t> x(n), left(n), right(n), result(n);
      std::atomic<int> init_count{0}, left_count{0}, right_count{0}, merge_count{0};
      auto init = graph.emplace([&] {
        for(size_t i=0; i<n; ++i) x[i] = ((std::int64_t(i)*37 + seed*11)%251)-125;
        ++init_count;
      }).name("initialize");
      auto lhs = graph.emplace([&] {
        for(size_t i=0; i<n; ++i) left[i] = x[i]*x[i]+3*x[i]+7;
        ++left_count;
      }).name("quadratic");
      auto rhs = graph.emplace([&] {
        for(size_t i=0; i<n; ++i) right[i] = 5*x[i]-11;
        ++right_count;
      }).name("linear");
      auto merge = graph.emplace([&] {
        for(size_t i=0; i<n; ++i) result[i] = left[i]-right[i];
        ++merge_count;
      }).name("merge");
      init.precede(lhs, rhs); lhs.precede(merge); rhs.precede(merge);
      executor.run_n(graph, 7).get();
      if(mutate && n == 17) ++result[0];
      std::cout << "{\"scenario\":\"dag\",\"n\":" << n << ",\"counts\":["
                << init_count << ',' << left_count << ',' << right_count << ',' << merge_count << "],\"result\":";
      vector_json(result); std::cout << "}\n";
    }
    for(int selection : {0,1,2,9}) {
      tf::Taskflow graph("conditional_branches");
      std::atomic<int> hits[3]{};
      std::int64_t output = -999;
      auto init = graph.emplace([]{});
      auto cond = graph.emplace([selection]{ return selection; });
      auto a = graph.emplace([&]{ output = seed*seed+1; ++hits[0]; });
      auto b = graph.emplace([&]{ output = seed*3-7; ++hits[1]; });
      auto c = graph.emplace([&]{ output = seed+23; ++hits[2]; });
      init.precede(cond); cond.precede(a,b,c);
      executor.run_n(graph, 7).get();
      std::cout << "{\"scenario\":\"branch\",\"selection\":" << selection << ",\"hits\":["
                << hits[0] << ',' << hits[1] << ',' << hits[2] << "],\"result\":" << output << "}\n";
    }
    for(int limit : {1,2,17,257}) {
      tf::Taskflow graph("conditional_loop");
      int iteration = 0, stops = 0;
      std::int64_t sum = 0;
      auto init = graph.emplace([&]{ iteration = 0; sum = seed; });
      auto cond = graph.emplace([&] {
        ++iteration; sum += (iteration*7 + seed)%97;
        return iteration < limit ? 0 : 1;
      });
      auto stop = graph.emplace([&]{ ++stops; });
      init.precede(cond); cond.precede(cond, stop);
      executor.run_n(graph, 3).get();
      std::cout << "{\"scenario\":\"loop\",\"limit\":" << limit << ",\"iterations\":" << iteration
                << ",\"stops\":" << stops << ",\"result\":" << sum << "}\n";
    }
    return 0;
  } catch(const std::exception& e) { std::cerr << e.what() << '\n'; return 2; }
}
