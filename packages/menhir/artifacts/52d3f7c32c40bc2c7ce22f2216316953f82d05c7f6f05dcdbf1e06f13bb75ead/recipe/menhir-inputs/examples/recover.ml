(* Explicit demonstration policy: delete an offending non-EOF token, then
   replay the last InputNeeded checkpoint. At most eight deletions are allowed.
   This is an example recovery policy, not a claim of language-correct repair. *)
module I = Calc.MenhirInterpreter

let token_name = function
  | Calc.INT _ -> "INT" | Calc.PLUS -> "PLUS" | Calc.MINUS -> "MINUS"
  | Calc.STAR -> "STAR" | Calc.SLASH -> "SLASH" | Calc.LPAREN -> "LPAREN"
  | Calc.RPAREN -> "RPAREN" | Calc.EOF -> "EOF"

let () =
  if Array.length Sys.argv <> 2 then exit 64;
  let buffer = Lexing.from_string Sys.argv.(1) in
  let repairs = ref [] in
  let saved = ref None in
  let offered = ref None in
  let fail state =
    Printf.eprintf "UNRECOVERABLE state=%d repairs=%d\n" state (List.length !repairs);
    exit 2
  in
  let rec drive checkpoint =
    match checkpoint with
    | I.InputNeeded _ ->
        let token = Lexer.token buffer in
        let first = buffer.Lexing.lex_start_p in
        let last = buffer.Lexing.lex_curr_p in
        saved := Some checkpoint;
        offered := Some (token, first, last);
        drive (I.offer checkpoint (token, first, last))
    | I.Shifting _ | I.AboutToReduce _ -> drive (I.resume checkpoint)
    | I.HandlingError env ->
        let state = I.current_state_number env in
        begin match !saved, !offered with
        | Some previous, Some (token, first, last)
          when token <> Calc.EOF && List.length !repairs < 8 ->
            repairs := (state, first.Lexing.pos_cnum, last.Lexing.pos_cnum,
                        token_name token) :: !repairs;
            drive previous
        | _ -> fail state
        end
    | I.Accepted value ->
        let entries = List.rev_map
          (fun (state, first, last, token) -> Printf.sprintf
             "{\"state\":%d,\"start_byte\":%d,\"end_byte\":%d,\"deleted_token\":\"%s\"}"
             state first last token) !repairs in
        Printf.printf "{\"value\":%d,\"recoveries\":[%s]}\n" value (String.concat "," entries)
    | I.Rejected -> fail (-1)
  in
  try drive (Calc.Incremental.main buffer.Lexing.lex_curr_p)
  with
  | Lexer.Invalid_character (c, byte) ->
      Printf.eprintf "LEXICAL_ERROR character=%C byte=%d\n" c byte; exit 2
  | Division_by_zero -> Printf.eprintf "DIVISION_BY_ZERO\n"; exit 3
