// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// Derived from LLVM 23.1.4 OrcV2Examples. See the accompanying LLVM license.
#include "llvm/AsmParser/Parser.h"
#include "llvm/ExecutionEngine/JITLink/JITLinkMemoryManager.h"
#include "llvm/ExecutionEngine/Orc/LLJIT.h"
#include "llvm/ExecutionEngine/Orc/ObjectLinkingLayer.h"
#include "llvm/Support/InitLLVM.h"
#include "llvm/Support/SourceMgr.h"
#include "llvm/Support/TargetSelect.h"
#include "llvm/Support/raw_ostream.h"
#include <cstdint>
#include <memory>

using namespace llvm;
using namespace llvm::orc;
static std::int64_t Calls = 0;
extern "C" std::int64_t cpg_host_transform(std::int64_t x) {
  ++Calls;
  return 3 * x + 7;
}

int main(int argc, char **argv) {
  InitLLVM Init(argc, argv);
  InitializeNativeTarget();
  InitializeNativeTargetAsmPrinter();
  ExitOnError Fail;
  auto Builder = Fail(JITTargetMachineBuilder::detectHost());
  Builder.setCodeModel(CodeModel::Small);
  auto J = Fail(LLJITBuilder()
      .setJITTargetMachineBuilder(std::move(Builder))
      .setObjectLinkingLayerCreator(
          [](ExecutionSession &ES, jitlink::JITLinkMemoryManager &MM) {
            return std::make_unique<ObjectLinkingLayer>(ES, MM);
          }).create());
  auto &JD = J->getMainJITDylib();
  Fail(JD.define(absoluteSymbols({
      {J->mangleAndIntern("cpg_host_transform"),
       {ExecutorAddr::fromPtr(&cpg_host_transform),
        JITSymbolFlags::Exported | JITSymbolFlags::Callable}}})));
  auto Context = std::make_unique<LLVMContext>();
  SMDiagnostic Diagnostic;
  auto Module = parseAssemblyString(R"(
    declare i64 @cpg_host_transform(i64)
    define i64 @cpg_entry(i64 %x) {
      %y = call i64 @cpg_host_transform(i64 %x)
      ret i64 %y
    }
  )", Diagnostic, *Context);
  if (!Module) { Diagnostic.print(argv[0], errs()); return 2; }
  Module->setDataLayout(J->getDataLayout());
  auto Tracker = JD.createResourceTracker();
  Fail(J->addIRModule(Tracker,
      ThreadSafeModule(std::move(Module), std::move(Context))));
  auto Entry = Fail(J->lookup("cpg_entry")).toPtr<std::int64_t(std::int64_t)>();
  for (std::int64_t x = -1000; x <= 1000; ++x)
    if (Entry(x) != 3*x+7) { errs() << "incorrect result\n"; return 3; }
  if (Calls != 2001) return 4;
  auto Absent = J->lookup("cpg_symbol_that_does_not_exist");
  if (Absent) return 5;
  consumeError(Absent.takeError());
  Fail(Tracker->remove());
  auto Removed = J->lookup("cpg_entry");
  if (Removed) return 6;
  consumeError(Removed.takeError());
  outs() << "ORC_JITLINK_PASS cases=2001 host_calls=2001 "
            "missing_symbol_rejected=1 removed_symbol_absent=1\n";
  return 0;
}
