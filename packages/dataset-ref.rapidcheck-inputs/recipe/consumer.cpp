#include <rapidcheck.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <numeric>
#include <string>
#include <vector>
int main(int argc, char **argv) {
    if (argc == 2 && !std::strcmp(argv[1], "--cpg-fail")) {
        const bool accepted = rc::check("intentionally incorrect increment identity", [](int value) {
            RC_ASSERT(std::int64_t(value) == std::int64_t(value) + 1);
        });
        if (!accepted) { std::cout << "deliberate property failure detected\n"; return 1; }
        return 0;
    }
    int runs = 0;
    const bool reversed = rc::check("double reversal preserves every element", [&](const std::vector<int> &input) {
        ++runs;
        auto values = input;
        std::reverse(values.begin(), values.end());
        std::reverse(values.begin(), values.end());
        RC_ASSERT(values == input);
    });
    const bool sorted = rc::check("sorting preserves values and produces order", [&](const std::vector<int> &input) {
        ++runs;
        auto values = input;
        std::sort(values.begin(), values.end());
        RC_ASSERT(std::is_sorted(values.begin(), values.end()));
        RC_ASSERT(std::is_permutation(input.begin(), input.end(), values.begin(), values.end()));
    });
    const bool append = rc::check("concatenation preserves both operand lengths", [&](const std::string &a, const std::string &b) {
        ++runs;
        RC_ASSERT((a + b).size() == a.size() + b.size());
    });
    const bool arithmetic = rc::check("widened integer addition is commutative", [&](int a, int b) {
        ++runs;
        RC_ASSERT(std::int64_t(a) + std::int64_t(b) == std::int64_t(b) + std::int64_t(a));
    });
    if (!(reversed && sorted && append && arithmetic) || runs != 400) return 2;
    std::cout << "{\"status\":\"passed\",\"properties\":4,\"executed_cases\":" << runs << "}\n";
}
