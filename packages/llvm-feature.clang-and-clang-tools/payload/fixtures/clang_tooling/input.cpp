#ifndef CPG_REAL_COMPILE_COMMAND
#error This fixture must be parsed through compile_commands.json
#endif

namespace cpg {
int old_api(int value) { return value + 7; }
double old_api(double value) { return value + 0.5; }
int new_api(int value) { return value + 7; }
}
namespace other {
int old_api(int value) { return value + 11; }
}
struct Local { int old_api(int value) { return value + 13; } };
#define CPG_OLD_MACRO(value) cpg::old_api(value)

int main() {
    // Preserve this comment: cpg::old_api(999).
    const char *message = "cpg::old_api(999)";
    Local local;
    using cpg::old_api;
    int a = cpg::old_api(3);
    int b = old_api(4);
    double untouched_overload = cpg::old_api(1.5);
    int untouched_namespace = other::old_api(1);
    int untouched_member = local.old_api(1);
    int untouched_macro = CPG_OLD_MACRO(5);
    return (a == 10 && b == 11 && untouched_overload == 2.0 &&
            untouched_namespace == 12 && untouched_member == 14 &&
            untouched_macro == 12 && message[0] == 'c') ? 0 : 1;
}
