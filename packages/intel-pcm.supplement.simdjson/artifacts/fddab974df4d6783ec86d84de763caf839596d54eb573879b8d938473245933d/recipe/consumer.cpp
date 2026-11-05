#include <simdjson.h>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <string_view>
static int checks = 0;
static void check(bool value, const char *label) {
    ++checks;
    if (!value) { std::cerr << "check failed: " << label << '\n'; std::exit(2); }
}
int main(int argc, char **argv) {
    if (argc == 2 && !std::strcmp(argv[1], "--cpg-fail")) {
        simdjson::dom::parser p;
        std::int64_t actual = 0;
        auto error = p.parse(std::string("{\"answer\":42}"))["answer"].get_int64().get(actual);
        if (!error && actual != 43) { std::cout << "deliberate answer mismatch detected\n"; return 1; }
        return 0;
    }
    simdjson::dom::parser parser;
    simdjson::dom::element document;
    const std::string json = R"({"answer":42,"negative":-17,"large":18446744073709551615,"ratio":1.25,"text":"\u4e2d\ud83d\ude00","values":[2,3,5],"flag":true,"nothing":null,"nested":{"x":9}})";
    check(!parser.parse(json).get(document), "parse valid object");
    std::int64_t integer = 0;
    check(!document["answer"].get_int64().get(integer) && integer == 42, "known integer");
    check(!document["negative"].get_int64().get(integer) && integer == -17, "negative integer");
    std::uint64_t large = 0;
    check(!document["large"].get_uint64().get(large) && large == UINT64_MAX, "uint64 boundary");
    double ratio = 0;
    check(!document["ratio"].get_double().get(ratio) && ratio == 1.25, "exact fraction");
    std::string_view text;
    check(!document["text"].get_string().get(text) && text == "\xe4\xb8\xad\xf0\x9f\x98\x80", "Unicode escapes");
    simdjson::dom::array array;
    check(!document["values"].get_array().get(array) && array.size() == 3, "array length");
    std::int64_t total = 0;
    for (auto item : array) { std::int64_t n = 0; if (item.get_int64().get(n)) return 2; total += n; }
    check(total == 10, "array values");
    bool flag = false;
    check(!document["flag"].get_bool().get(flag) && flag, "boolean");
    check(document["nothing"].is_null(), "null");
    check(!document.at_pointer("/nested/x").get_int64().get(integer) && integer == 9, "JSON pointer");
    check(document["missing"].error() == simdjson::NO_SUCH_FIELD, "missing field");
    check(document["text"].get_int64().error() == simdjson::INCORRECT_TYPE, "type mismatch");
    const std::string bad_utf8("\xc0\xaf", 2);
    check(!simdjson::validate_utf8(bad_utf8.data(), bad_utf8.size()), "invalid UTF-8");
    int rejected = 0;
    for (const std::string invalid : {std::string("{\"a\":"), std::string("[1,]"), std::string("{\"a\":01}"), std::string("\"\\uD800\"")}) {
        simdjson::dom::parser invalid_parser;
        simdjson::dom::element result;
        const bool refused = bool(invalid_parser.parse(invalid).get(result));
        check(refused, "invalid JSON rejection");
        if (refused) ++rejected;
    }
    std::cout << "{\"status\":\"passed\",\"checks\":" << checks
              << ",\"invalid_inputs_rejected\":" << rejected << "}\n";
    return checks == 18 && rejected == 4 ? 0 : 2;
}
