// CPG integration fixture (MIT). Uses the unmodified upstream Example dialect.
#include "ExampleDialect.h"
#include "llvm-dialects/Dialect/Verifier.h"
#include "llvm/AsmParser/Parser.h"
#include "llvm/IR/Constants.h"
#include "llvm/IR/InstIterator.h"
#include "llvm/IR/Module.h"
#include "llvm/IR/Verifier.h"
#include "llvm/Support/SourceMgr.h"
#include "llvm/Support/raw_ostream.h"
#include <cstdint>
#include <map>
#include <vector>
using namespace llvm;

static uint32_t evaluate(Function &fn, uint32_t input) {
  std::map<const Value *, uint32_t> values;
  values[fn.getArg(0)] = input;
  auto get = [&](Value *v) -> uint32_t {
    if (auto *c = dyn_cast<ConstantInt>(v)) return c->getZExtValue();
    auto it = values.find(v);
    if (it == values.end()) report_fatal_error("Unsupported fixture value");
    return it->second;
  };
  for (Instruction &inst : instructions(fn)) {
    if (auto *op = dyn_cast<xd::cpp::Add32Op>(&inst)) {
      values[op] = get(op->getLhs()) + get(op->getRhs()) + op->getExtra();
    } else if (auto *ret = dyn_cast<ReturnInst>(&inst)) {
      return get(ret->getReturnValue());
    } else report_fatal_error("Unsupported fixture instruction");
  }
  report_fatal_error("Fixture has no return");
}

int main(int argc, char **argv) {
  if (argc != 2) { errs() << "usage: cpg-dialects-rewrite input.ll\n"; return 2; }
  LLVMContext context;
  auto dialectContext = llvm_dialects::DialectContext::make<xd::cpp::ExampleDialect>(context);
  SMDiagnostic diagnostic;
  auto module = parseAssemblyFile(argv[1], diagnostic, context);
  if (!module) { diagnostic.print(argv[0], errs()); return 3; }
  if (verifyModule(*module, &errs()) || !llvm_dialects::verify(*module, errs())) return 4;
  auto *positive = module->getFunction("positive");
  auto *negative = module->getFunction("negative_no_match");
  if (!positive || !negative) return 5;
  std::vector<uint32_t> inputs = {0, 1, 7, 42, 0x7fffffffU, 0x80000000U, 0xffffffffU};
  std::vector<uint32_t> beforePositive, beforeNegative;
  for (auto x : inputs) {
    beforePositive.push_back(evaluate(*positive, x));
    beforeNegative.push_back(evaluate(*negative, x));
  }
  unsigned changed = 0;
  for (Function &fn : *module) {
    std::vector<Instruction *> remove;
    for (Instruction &inst : instructions(fn)) {
      auto *op = dyn_cast<xd::cpp::Add32Op>(&inst);
      if (!op) continue;
      auto *rhs = dyn_cast<ConstantInt>(op->getRhs());
      if (rhs && rhs->isZero() && op->getExtra() == 0) {
        op->replaceAllUsesWith(op->getLhs());
        remove.push_back(op);
      }
    }
    for (auto *inst : remove) { inst->eraseFromParent(); ++changed; }
  }
  if (changed != 1 || verifyModule(*module, &errs()) || !llvm_dialects::verify(*module, errs())) return 6;
  for (size_t i = 0; i < inputs.size(); ++i) {
    if (evaluate(*positive, inputs[i]) != beforePositive[i] || evaluate(*negative, inputs[i]) != beforeNegative[i] || beforePositive[i] != inputs[i] || beforeNegative[i] != uint32_t(inputs[i]+7U)) return 7;
  }
  errs() << "CPG_DIALECTS_PASS changed=1 comparisons=14 negative_preserved=1\n";
  module->print(outs(), nullptr);
  return 0;
}
