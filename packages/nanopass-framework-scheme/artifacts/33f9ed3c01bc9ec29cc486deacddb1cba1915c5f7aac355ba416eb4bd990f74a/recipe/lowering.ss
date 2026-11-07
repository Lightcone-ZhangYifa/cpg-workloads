#!r6rs
;; CPG authored verification fixture, MIT licensed.
;; Both languages and the lowering are implemented with the upstream framework.
(import (chezscheme) (nanopass))

(define (integer-literal? x) (and (integer? x) (exact? x)))
(define-language Lhigh
  (terminals (integer-literal (n)))
  (Expr (e)
    n
    (add e0 e1)
    (mul e0 e1)
    (inc e)))
(define-language Llow
  (extends Lhigh)
  (Expr (e) (- (inc e))))
(define-parser parse-high Lhigh)
(define-parser parse-low Llow)
(define-pass lower-inc : Lhigh (ir) -> Llow ()
  (Expr : Expr (ir) -> Expr ()
    [(inc ,[e]) `(add ,e 1)]))

;; Independent source/target evaluators operate on S-expressions, not on the
;; lowering implementation. Arithmetic is exact integer arithmetic.
(define (eval-high e)
  (cond
    [(integer-literal? e) e]
    [else
      (case (car e)
        [(inc) (+ 1 (eval-high (cadr e)))]
        [(add) (+ (eval-high (cadr e)) (eval-high (caddr e)))]
        [(mul) (* (eval-high (cadr e)) (eval-high (caddr e)))]
        [else (error 'eval-high "invalid source operator" e)])]))
(define (eval-low e)
  (cond
    [(integer-literal? e) e]
    [else
      (case (car e)
        [(add) (+ (eval-low (cadr e)) (eval-low (caddr e)))]
        [(mul) (* (eval-low (cadr e)) (eval-low (caddr e)))]
        [else (error 'eval-low "invalid target operator" e)])]))

(define (assert-true x reason)
  (unless x (error 'cpg-nanopass reason)))
(define (rejects? parser value)
  (guard (exn [else #t]) (parser value) #f))
(define (no-inc? x)
  (or (not (pair? x))
      (and (not (eq? (car x) 'inc)) (for-all no-inc? x))))

(define checked 0)
(define (check-expression source)
  (let* ([parsed (parse-high source)]
         [target (unparse-Llow (lower-inc parsed))])
    (assert-true (equal? source (unparse-Lhigh parsed)) "source round trip changed shape")
    (assert-true (equal? target (unparse-Llow (parse-low target))) "target parser rejected output")
    (assert-true (no-inc? target) "forbidden source-only construct survived lowering")
    (assert-true (= (eval-high source) (eval-low target)) "semantic mismatch")
    (set! checked (+ 1 checked))))

;; Enumerate all depth-one cases over five constants, then stress deterministic
;; nested trees. This is a bounded suite, not a proof for every program.
(define constants '(-9 -1 0 1 17))
(for-each check-expression constants)
(for-each (lambda (x) (check-expression `(inc ,x))) constants)
(for-each (lambda (a)
  (for-each (lambda (b)
    (check-expression `(add ,a ,b))
    (check-expression `(mul ,a ,b))
    (check-expression `(inc (add (inc ,a) (mul ,b (inc ,a)))))) constants)) constants)
(define (tree depth seed)
  (if (= depth 0) (- (modulo seed 37) 18)
    (case (modulo seed 3)
      [(0) `(inc ,(tree (- depth 1) (+ (* seed 5) 1)))]
      [(1) `(add ,(tree (- depth 1) (+ (* seed 3) 2))
                ,(tree (- depth 1) (+ (* seed 7) 3)))]
      [else `(mul ,(tree (- depth 1) (+ (* seed 2) 5))
                  ,(tree (- depth 1) (+ (* seed 11) 7)))])))
(do ([seed 0 (+ seed 1)]) ((= seed 128)) (check-expression (tree 5 seed)))

(define invalid-high '((inc 1 2) (add 1) (mul 1 2 3) (unknown 1) (add 1 "bad") ()))
(define invalid-low '((inc 1) (add 1) (mul 1 2 3) (unknown 1) (add 1 "bad") ()))
(for-each (lambda (x) (assert-true (rejects? parse-high x) "invalid source was accepted")) invalid-high)
(for-each (lambda (x) (assert-true (rejects? parse-low x) "invalid target was accepted")) invalid-low)
(assert-true (equal? (unparse-Llow (lower-inc (parse-high '(inc (mul 6 7))))) '(add (mul 6 7) 1))
             "exact lowering output differed")
(printf "{\"status\":\"passed\",\"semantic_cases\":~a,\"negative_shape_cases\":~a,\"ir_count\":2,\"pass_count\":1,\"scope\":\"exact integer inc lowering, bounded trees\"}\n"
  checked (+ (length invalid-high) (length invalid-low)))
