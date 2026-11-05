#include <cstdint>
#include <iostream>
#include <limits>
#include <vector>
#include "libdivide.h"

template<class T> unsigned check_type() {
    const T lo = std::numeric_limits<T>::min();
    const T hi = std::numeric_limits<T>::max();
    std::vector<T> numerators{lo, T(lo + 1), T(0), T(1), T(2), T(31), T(hi / 2), T(hi - 1), hi};
    std::vector<T> denominators{T(1), T(2), T(3), T(7), T(31), T(hi / 2 + 1), hi};
    if (std::numeric_limits<T>::is_signed) {
        numerators.push_back(T(-1));
        numerators.push_back(T(-100));
        denominators.push_back(T(-1));
        denominators.push_back(T(-31));
        denominators.push_back(lo);
    }
    unsigned count = 0;
    for (T denominator : denominators) {
        libdivide::divider<T> divisor(denominator);
        if (divisor.recover() != denominator) throw "divisor recovery failed";
        for (T numerator : numerators) {
            if (std::numeric_limits<T>::is_signed && numerator == lo && denominator == T(-1)) continue;
            if (numerator / divisor != numerator / denominator) throw "branchfull division failed";
            ++count;
        }
        if (!std::numeric_limits<T>::is_signed && denominator == 1) continue;
        libdivide::branchfree_divider<T> branchfree(denominator);
        for (T numerator : numerators) {
            if (std::numeric_limits<T>::is_signed && numerator == lo && denominator == T(-1)) continue;
            if (numerator / branchfree != numerator / denominator) throw "branchfree division failed";
            ++count;
        }
    }
    return count;
}

int main() {
    const unsigned count = check_type<std::int16_t>() + check_type<std::uint16_t>() +
                           check_type<std::int32_t>() + check_type<std::uint32_t>() +
                           check_type<std::int64_t>() + check_type<std::uint64_t>();
    std::cout << "libdivide C++ " << LIBDIVIDE_VERSION << ": " << count << " comparisons passed\n";
}
