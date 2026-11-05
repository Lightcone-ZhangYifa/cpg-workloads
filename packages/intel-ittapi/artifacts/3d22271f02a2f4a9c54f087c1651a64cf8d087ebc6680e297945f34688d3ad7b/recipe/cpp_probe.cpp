#include "ittapi.hpp"
int main() {
    ittapi::set_thread_name("cpg-cpp-worker");
    ittapi::Domain domain("cpg-cpp-domain");
    auto task = domain.task("cpg-cpp-task");
    task.end();
    return 0;
}
