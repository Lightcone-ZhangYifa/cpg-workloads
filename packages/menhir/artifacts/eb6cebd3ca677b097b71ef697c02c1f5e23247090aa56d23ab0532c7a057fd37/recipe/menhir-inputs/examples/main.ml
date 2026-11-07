let () =
  if Array.length Sys.argv <> 2 then exit 64;
  let buffer = Lexing.from_string Sys.argv.(1) in
  try Printf.printf "%d\n" (Calc.main Lexer.token buffer)
  with
  | Calc.Error ->
      Printf.eprintf "SYNTAX_ERROR byte=%d\n" (Lexing.lexeme_start buffer); exit 2
  | Lexer.Invalid_character (c, byte) ->
      Printf.eprintf "LEXICAL_ERROR character=%C byte=%d\n" c byte; exit 2
  | Division_by_zero -> Printf.eprintf "DIVISION_BY_ZERO\n"; exit 3
