/* Intentionally ambiguous: diagnostics are the expected result. */
%token <int> INT
%token PLUS STAR EOF
%start <int> main
%type <int> expr
%%
main: value=expr EOF { value }
expr:
  value=INT { value }
| left=expr PLUS right=expr { left + right }
| left=expr STAR right=expr { left * right }
