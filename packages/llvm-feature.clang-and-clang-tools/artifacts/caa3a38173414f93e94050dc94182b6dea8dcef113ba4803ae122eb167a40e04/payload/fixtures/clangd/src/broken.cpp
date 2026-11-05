#include "api.hpp"
int broken() {
    return cpg::add(1, "wrong-type");
}
