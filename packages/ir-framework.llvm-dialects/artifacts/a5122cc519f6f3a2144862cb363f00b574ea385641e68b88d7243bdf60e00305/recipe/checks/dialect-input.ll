declare i32 @xd.ir.add32(i32, i32, i32)
define i32 @positive(i32 %x) {
  %r = call i32 @xd.ir.add32(i32 %x, i32 0, i32 0)
  ret i32 %r
}
define i32 @negative_no_match(i32 %x) {
  %r = call i32 @xd.ir.add32(i32 %x, i32 0, i32 7)
  ret i32 %r
}
