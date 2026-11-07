include "mlir/IR/OpBase.td"
include "mlir/Interfaces/SideEffectInterfaces.td"
def Cpg_Dialect : Dialect {
  let name = "cpg";
  let cppNamespace = "::cpg";
}
def Cpg_IdentityOp : Op<Cpg_Dialect, "identity", [Pure]> {
  let arguments = (ins I32:$input);
  let results = (outs I32:$output);
}
