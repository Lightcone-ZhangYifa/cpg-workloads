module @ir {
  func.func @positive(%arg: i32) -> i32 {
    %r = "cpg.identity"(%arg) : (i32) -> i32
    return %r : i32
  }
  func.func @negative_no_match(%arg: i32) -> i32 {
    %c = arith.constant 7 : i32
    %r = arith.addi %arg, %c : i32
    return %r : i32
  }
}
