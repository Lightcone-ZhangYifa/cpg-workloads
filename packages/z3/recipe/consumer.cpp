#include <z3++.h>
#include <iostream>
#include <stdexcept>
#include <string>

static void require(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

int main() {
    try {
        z3::context context;
        unsigned checks = 0, rejected = 0;
        {
            z3::solver solver(context);
            auto x = context.int_const("x");
            solver.add(x > 40 && x < 43 && x % 2 == 0);
            require(solver.check() == z3::sat, "integer SAT oracle");
            require(solver.get_model().eval(x).get_numeral_int() == 42, "integer model oracle");
            ++checks;
            solver.push(); solver.add(x != 42);
            require(solver.check() == z3::unsat, "contradictory model must be UNSAT");
            ++checks;
            solver.pop(); require(solver.check() == z3::sat, "pop must restore SAT");
            ++checks;
        }
        {
            z3::solver solver(context);
            auto x = context.bv_const("bits", 8);
            solver.add(x * 2 == 10); solver.add(z3::ult(x, context.bv_val(10, 8)));
            require(solver.check() == z3::sat, "bit-vector SAT oracle");
            require(solver.get_model().eval(x).get_numeral_int() == 5, "bit-vector model oracle");
            ++checks;
        }
        {
            z3::solver solver(context);
            auto array = context.constant("a", context.array_sort(context.int_sort(), context.int_sort()));
            auto updated = z3::store(array, context.int_val(7), context.int_val(42));
            solver.add(z3::select(updated, context.int_val(7)) != 42);
            require(solver.check() == z3::unsat, "array store/select oracle"); ++checks;
        }
        {
            z3::solver solver(context);
            auto x = context.real_const("r");
            solver.add(x / 2 == 3);
            require(solver.check() == z3::sat, "real SAT oracle");
            require(solver.get_model().eval(x).to_string() == "6.0", "rational model oracle");
            ++checks;
        }
        {
            z3::solver solver(context);
            auto x = context.int_const("core_x");
            z3::expr assumptions[] = {x > 0, x < 0};
            require(solver.check(2, assumptions) == z3::unsat, "assumptions UNSAT oracle");
            require(solver.unsat_core().size() == 2, "unsat core oracle"); ++checks;
        }
        {
            z3::solver solver(context);
            solver.from_string("(declare-const n Int) (assert (> n 2)) (assert (< n 3))");
            require(solver.check() == z3::unsat, "SMT-LIB parser oracle"); ++checks;
        }
        for (const char *malformed : {
            "(assert (= #b1 #b10))",
            "(assert (+",
            "(assert cpg_definitely_missing_bool_symbol)"}) {
            z3::solver solver(context); bool caught = false;
            try { solver.from_string(malformed); }
            catch (const z3::exception &) { caught = true; }
            require(caught, "malformed SMT-LIB must throw"); ++rejected;
        }
        unsigned major, minor, build, revision;
        Z3_get_version(&major, &minor, &build, &revision);
        std::cout << "{\"checks\":" << checks << ",\"invalid_inputs_rejected\":" << rejected
                  << ",\"version\":\"" << major << '.' << minor << '.' << build
                  << "\",\"status\":\"passed\"}\n";
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n'; return 1;
    }
    return 0;
}
