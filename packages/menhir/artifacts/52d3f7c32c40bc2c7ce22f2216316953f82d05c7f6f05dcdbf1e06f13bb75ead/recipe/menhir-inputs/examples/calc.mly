/* CPG worker001 demonstration, MIT license; authored for this integration. */
%token <int> INT
%token PLUS MINUS STAR SLASH LPAREN RPAREN EOF
%left PLUS MINUS
%left STAR SLASH
%nonassoc UMINUS
%start <int> main
%%
main:
  value = expr; EOF { value }
expr:
  value = INT { value }
| left = expr; PLUS; right = expr { left + right }
| left = expr; MINUS; right = expr { left - right }
| left = expr; STAR; right = expr { left * right }
| left = expr; SLASH; right = expr { left / right }
| MINUS; value = expr %prec UMINUS { -value }
| LPAREN; value = expr; RPAREN { value }
