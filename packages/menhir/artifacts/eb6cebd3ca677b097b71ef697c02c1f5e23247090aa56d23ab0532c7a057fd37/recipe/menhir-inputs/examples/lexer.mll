{
open Calc
exception Invalid_character of char * int
}
rule token = parse
| [' ' '\t' '\r' '\n'] { token lexbuf }
| ['0'-'9']+ as n { INT (int_of_string n) }
| '+' { PLUS }
| '-' { MINUS }
| '*' { STAR }
| '/' { SLASH }
| '(' { LPAREN }
| ')' { RPAREN }
| eof { EOF }
| _ as c { raise (Invalid_character (c, Lexing.lexeme_start lexbuf)) }
