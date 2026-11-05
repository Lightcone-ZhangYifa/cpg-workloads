#include <simdjson.h>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
  if (argc == 2 && std::string(argv[1]) == "--list") {
    for (auto implementation : simdjson::get_available_implementations()) {
      if (implementation->supported_by_runtime_system()) std::cout << implementation->name() << "\n";
    }
    return 0;
  }
  if (argc != 2) return 64;
  auto implementation = simdjson::get_available_implementations()[argv[1]];
  if (!implementation || !implementation->supported_by_runtime_system()) {
    std::cerr << "Unsupported implementation\n"; return 65;
  }
  simdjson::get_active_implementation() = implementation;
  // Exercise On-Demand independently of the streaming DOM round-trip below.
  simdjson::ondemand::parser ondemand;
  simdjson::padded_string example(std::string("{\"key\":42,\"array\":[1,2,3]}"));
  auto document = ondemand.iterate(example);
  int64_t value = 0;
  if (document["key"].get_int64().get(value) || value != 42) return 66;
  simdjson::dom::parser parser;
  std::string line;
  size_t count = 0;
  while (std::getline(std::cin, line)) {
    simdjson::padded_string input(line);
    simdjson::dom::element element;
    auto error = parser.parse(input).get(element);
    if (error) { std::cerr << "Parse failed: " << simdjson::error_message(error) << "\n"; return 2; }
    std::cout << simdjson::to_string(element) << "\n";
    ++count;
  }
  if (!count) return 67;
  std::cerr << "implementation=" << simdjson::get_active_implementation()->name() << " documents=" << count << "\n";
  return 0;
}
