// SPDX-License-Identifier: MIT
// A deliberately bounded source transformation using the real Clang APIs.
#include "clang/ASTMatchers/ASTMatchFinder.h"
#include "clang/ASTMatchers/ASTMatchers.h"
#include "clang/Tooling/CommonOptionsParser.h"
#include "clang/Tooling/Refactoring/AtomicChange.h"
#include "clang/Tooling/Tooling.h"
#include "clang/Tooling/Transformer/RangeSelector.h"
#include "clang/Tooling/Transformer/RewriteRule.h"
#include "clang/Tooling/Transformer/Stencil.h"
#include "clang/Tooling/Transformer/Transformer.h"
#include "llvm/Support/MemoryBuffer.h"
#include "llvm/Support/Path.h"
#include "llvm/Support/raw_ostream.h"
#include <cctype>

using namespace clang;
using namespace clang::ast_matchers;
using namespace clang::tooling;
using namespace clang::transformer;

namespace clang::ast_matchers {
AST_MATCHER(CallExpr, isDirectFileSpelling) {
  return !Node.getBeginLoc().isMacroID() &&
         !Node.getCallee()->getExprLoc().isMacroID() &&
         !Node.getEndLoc().isMacroID();
}
} // namespace clang::ast_matchers

static llvm::cl::OptionCategory Category("CPG semantic rewrite");
static llvm::cl::opt<std::string> FromQualified(
    "from-qualified", llvm::cl::desc("Exact qualified source function name"),
    llvm::cl::init("::cpg::old_api"), llvm::cl::cat(Category));
static llvm::cl::opt<std::string> ToQualified(
    "to-qualified", llvm::cl::desc("Qualified replacement function name"),
    llvm::cl::init("::cpg::new_api"), llvm::cl::cat(Category));
static llvm::cl::opt<std::string> ParameterType(
    "parameter-type", llvm::cl::desc("Exact Clang type spelling of the single parameter"),
    llvm::cl::init("int"), llvm::cl::cat(Category));
static llvm::cl::opt<std::string> ReturnType(
    "return-type", llvm::cl::desc("Exact Clang return type spelling"),
    llvm::cl::init("int"), llvm::cl::cat(Category));
static llvm::cl::opt<int> ExpectedCount(
    "expected-count", llvm::cl::desc("Require this many matches; -1 accepts any count"),
    llvm::cl::init(-1), llvm::cl::cat(Category));

static bool validQualifiedName(llvm::StringRef Name) {
  if (!Name.consume_front("::") || Name.empty())
    return false;
  while (!Name.empty()) {
    auto [Part, Rest] = Name.split("::");
    if (Part.empty() || !(std::isalpha(static_cast<unsigned char>(Part.front())) || Part.front() == '_'))
      return false;
    for (char Ch : Part)
      if (!(std::isalnum(static_cast<unsigned char>(Ch)) || Ch == '_'))
        return false;
    if (!Rest.empty())
      Name = Rest;
    else
      return !Name.ends_with("::");
  }
  return true;
}

int main(int argc, const char **argv) {
  auto Options = CommonOptionsParser::create(argc, argv, Category);
  if (!Options) {
    llvm::errs() << llvm::toString(Options.takeError()) << "\n";
    return 2;
  }
  if (!validQualifiedName(FromQualified) || !validQualifiedName(ToQualified)) {
    llvm::errs() << "Function names must use ::namespace::identifier syntax.\n";
    return 2;
  }
  const auto &Sources = Options->getSourcePathList();
  if (Sources.size() != 1) {
    llvm::errs() << "Exactly one translation unit is required.\n";
    return 2;
  }
  // Never silently substitute fallback flags when a compilation entry is absent.
  if (Options->getCompilations().getCompileCommands(Sources[0]).empty()) {
    llvm::errs() << "No compilation database entry for the requested TU.\n";
    return 2;
  }
  auto Input = llvm::MemoryBuffer::getFile(Sources[0]);
  if (!Input) {
    llvm::errs() << Input.getError().message() << "\n";
    return 2;
  }
  std::vector<AtomicChange> Changes;
  bool Failed = false;
  // Only calls to the exact namespace and int overload are rewritten. Text,
  // comments, the double overload, other namespaces, members and macros stay.
  auto Target = functionDecl(hasName(FromQualified), parameterCountIs(1),
                             hasParameter(0, hasType(asString(ParameterType))),
                             returns(asString(ReturnType)));
  auto Rule = makeRule(
      callExpr(callee(Target), callee(expr().bind("callee")),
               isExpansionInMainFile(), isDirectFileSpelling()),
      changeTo(node("callee"), cat(ToQualified)));
  Transformer Transform(
      std::move(Rule),
      [&](llvm::Expected<llvm::MutableArrayRef<AtomicChange>> Result) {
        if (!Result) {
          llvm::errs() << llvm::toString(Result.takeError()) << "\n";
          Failed = true;
          return;
        }
        for (auto &Change : *Result)
          Changes.push_back(std::move(Change));
      });
  MatchFinder Finder;
  Transform.registerMatchers(&Finder);
  ClangTool Tool(Options->getCompilations(), Sources);
  if (Tool.run(newFrontendActionFactory(&Finder).get()) != 0 || Failed)
    return 3;
  if (ExpectedCount >= 0 && Changes.size() != static_cast<size_t>(ExpectedCount)) {
    llvm::errs() << "Expected " << ExpectedCount << " matches, found " << Changes.size() << ".\n";
    return 5;
  }
  ApplyChangesSpec Spec;
  Spec.Cleanup = false;
  Spec.Format = ApplyChangesSpec::kNone;
  auto Output = applyAtomicChanges(Sources[0], (*Input)->getBuffer(), Changes, Spec);
  if (!Output) {
    llvm::errs() << llvm::toString(Output.takeError()) << "\n";
    return 4;
  }
  llvm::outs() << *Output;
  llvm::errs() << "CPG_REWRITE_COUNT=" << Changes.size() << "\n";
  return 0;
}
