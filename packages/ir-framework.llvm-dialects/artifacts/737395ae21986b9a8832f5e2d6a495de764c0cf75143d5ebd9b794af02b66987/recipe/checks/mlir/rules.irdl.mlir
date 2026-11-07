module {
  irdl.dialect @cpg {
    irdl.operation @identity {
      %t = irdl.is i32
      irdl.operands(input: %t)
      irdl.results(output: %t)
    }
  }
}
