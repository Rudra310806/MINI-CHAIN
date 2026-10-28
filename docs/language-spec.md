# MiniChain Language Specification

## 1. Introduction

MiniChain is a domain-aware programming language designed for
applications involving financial transactions, supply-chain operations,
and voting/governance systems.

The language is designed to support:

- Lexical analysis
- Syntax analysis
- Semantic analysis
- Domain-specific validation
- Static analysis
- Code optimization
- Optimized code generation

The language uses a contract-based programming model.

---

## 2. Program Structure

Every MiniChain program consists of a contract.

Basic structure:

```text
contract <ContractName> {
    state declarations
    function declarations
}
```

The lexer accepts integer literals as digits and floating-point literals as
digits, a decimal point, and digits. Exponent notation is not accepted. The
code generator emits exponent-free decimal spelling for float values so its
output remains valid MiniChain source; this is a source-format rule and does
not define runtime floating-point semantics.

## 3. Domain-specific static analysis

Domain findings are heuristic `WARNING` diagnostics over the parsed AST. They
identify source patterns; they do not prove a contract is safe, correct, or
compliant. Rules recognize selected function and identifier names and may miss
equivalent code written with other names or control-flow shapes.

### Banking / Finance

Banking checks run for functions named `deposit`, `withdraw`, and `transfer`.
The existing rules search conditions recursively through `require`, `if`, and
`while` statements, and search assignment expressions for the expected balance
operation:

- `BANK-001` and `BANK-004`: a withdrawal or deposit condition contains
  `amount > 0` (or the reversed `0 < amount` form).
- `BANK-002`: a withdrawal condition contains `amount <= balance` or
  `balance >= amount`.
- `BANK-003`: a withdrawal assigns a subtraction of the declared amount
  parameter from `balance` back to `balance`.
- `BANK-005`: a deposit assigns an addition of `balance` and `amount` back to
  `balance`.
- `BANK-006` and `BANK-007`: a transfer condition contains a positive-amount
  check and a sufficient-balance check, respectively.
- `BANK-008`: a transfer assigns a subtraction of `amount` from `balance` back
  to `balance`.
- `BANK-009`: in a recognized function, a matching top-level `require` for a
  positive amount or sufficient balance appears only after the first
  top-level statement that assigns to `balance`.
- `BANK-010`: in a nested block of a recognized function, a matching amount
  or sufficient-balance `require` follows a balance write in that same block,
  unless an equivalent guard is already present in the enclosing path or
  controlling `if`/`while` condition. A guard comparison inside `&&` counts;
  one found only inside `||` does not.

Amount checks use the exact spelling of a unique parameter whose name matches
`amount` without regard to case. The existing condition checks test presence,
not that the condition controls a write. `BANK-009` checks ordering at the
function body's top level; `BANK-010` checks a narrow nested-block ordering
case. Neither performs general branch-dominance analysis or proves transaction
behavior.

### Supply Chain

Supply Chain checks run only for recognized registration, dispatch, delivery,
and ownership-transfer function names. Status and owner fields are recognized
by the name sets in `domain_analyzer.py`.

- `SC-001`: registration has no assignment to a recognized status field.
- `SC-002`: dispatch has no condition mentioning a recognized status field.
- `SC-003`: delivery has no condition containing both a recognized status
  field and one of `dispatched`, `shipped`, or `in_transit`.
- `SC-004`: ownership transfer has no condition mentioning a recognized owner
  field.
- `SC-005`: dispatch does not assign a recognized status field the string
  `dispatched`, `shipped`, or `in_transit`.
- `SC-006`: delivery does not assign a recognized status field the string
  `delivered`.
- `SC-007`: ownership transfer does not assign a recognized owner field from
  an identifier declared as an `address` parameter of that function.
- `SC-008`: registration does not assign a recognized status field the string
  `registered` or `created`.
- `SC-009`: in a recognized dispatch or delivery function, a top-level
  assignment to a recognized next-state string appears before a top-level
  require for a recognized prior state. A direct equality or equality within
  `&&` counts; a comparison found only inside `||` does not. Dispatch
  recognizes `registered` or `created` as prior states; delivery recognizes
  `dispatched`, `shipped`, or `in_transit`.

The earlier rules do not pair a status check with a transition. The added
transition checks look for direct AST assignments, but do not model product
identity, multiple shipments, or valid custom lifecycle labels.
`SC-009` only checks the ordering of direct top-level assignments and requires;
it does not analyze nested control flow or prove that a status transition is
valid for a particular product.

### Voting / Governance

Voting checks run for recognized vote-submission function names.

- `VOTE-001`, `VOTE-002`, and `VOTE-003`: a condition mentions a recognized
  voting-period, eligibility, or duplicate-vote identifier, respectively.
- `VOTE-004`: an assignment targets a recognized vote-count or duplicate-vote
  identifier.
- `VOTE-005`: when both are present, a top-level `require(!flag)` or
  `require(flag == false)` for a recognized duplicate-vote flag follows an
  assignment setting that same, exactly spelled flag to `true`.
- `VOTE-006`: a vote-submission function has a direct top-level require of
  `!flag` or `flag == false` for a declared boolean with a recognized
  eligibility name.
- `VOTE-007`: a vote-submission function has a direct top-level require of
  `!flag` or `flag == false` for a declared boolean with a recognized
  voting-period name.

The original rules check identifier presence only. `VOTE-005` handles this
narrow direct-`require` sequence; it does not model alternative guard forms,
voter identity, ballot choices, or transaction atomicity. `VOTE-006` and
`VOTE-007` only identify direct, explicitly false boolean guards by source
pattern and recognized names; they may miss equivalent expressions and do not
prove the intended access or voting policy.

### Automatic repair coverage

Automatic Repair inserts selected guards or initializations for
`BANK-001`, `BANK-002`, `BANK-004`, `BANK-006`, `BANK-007`, `SC-001` through
`SC-003`, and `VOTE-001` through `VOTE-003`. It can also reorder a narrowly
recognized existing guard for `BANK-010` or `SC-009`: the direct matching
`require` must immediately follow its corresponding balance update in the
same nested block, or status transition in the same top-level sequence. The
guard must match the operation and identifiers exactly, and the source lines
must form one unique adjacent pair. The repair moves only those two statements;
it does not cross other statements or restructure control flow. Other shapes,
compound guards, ambiguous matches, and non-adjacent statements are skipped.

Each candidate is reanalyzed by the compiler. It is accepted only if compiler
validation succeeds and every targeted domain finding disappears. Otherwise
the original source is retained and the candidate is reported as rejected.
The API reports applied repairs, unsupported skips, and rejected candidates
separately. A successful repair response means the accepted candidate passed
revalidation; it does not mean that every domain finding was fixed. Remaining
unrelated findings are still reported.

The following findings have no automatic repair: `BANK-003`, `BANK-005`,
`BANK-008`, `BANK-009`, `SC-004` through `SC-008`, and `VOTE-004` through
`VOTE-007`. `VOTE-006` and `VOTE-007` describe direct false guards, but
identifier names do not define the intended eligibility or voting-period
policy, so their truth value is never changed automatically. Domain findings
remain heuristic warnings and are not security guarantees.

## 4. Numeric semantics status

MiniChain `int` values are arbitrary-precision signed mathematical integers.
Integer arithmetic does not overflow, wrap, or trap. Bitwise behavior,
floating-point representation, and integer-to-float conversion remain
unspecified.

For integer operands and a nonzero divisor, `/` returns the quotient truncated
toward zero. Integer `%` returns `a - quotient * b`, using that same truncated
quotient. For example, `7 / 2` is `3`, `-7 / 3` is `-2`, and `-7 % 3` is `-1`.
Division or modulo by zero has no defined runtime result. The optimizer leaves
zero-divisor expressions unchanged.

For integer shift operands, `a << n` means `a * 2**n`. Integer `>>` is an
arithmetic right shift that preserves the sign, equivalent to floor division
by `2**n`. Shift counts must be nonnegative; a negative shift count is invalid.
The current semantic analyzer checks that both operands have type `int`, but
does not diagnose negative counts, and no runtime engine is provided to define
their error handling.

Prefix and postfix updates are supported for writable `int` identifiers:
`++value`, `--value`, `value++`, and `value--`. Prefix updates change the
identifier by one and yield the updated value. Postfix updates change it by
one and yield its previous value. Each update reads and writes its identifier
once. Since `int` values are arbitrary-precision mathematical integers, these
updates do not overflow. Updates of non-`int` values and updates whose target
is not an identifier are invalid. The optimizer preserves update expressions
and does not rewrite them as arithmetic or count syntax support as an
optimization.

For an assignment statement whose integer target is also the direct identifier
operand, the optimizer may simplify `value = value + 1`, `value = 1 + value`,
and `value = value - 1` to the corresponding postfix update `value++` or
`value--`. The assignment's resulting expression value is unused, so the
postfix form has the same observable update in statement context; it evaluates
the integer variable once and performs one update. This exact rewrite is
reported as `OPT-027`. Other operands, non-integer targets, non-integer
literals, and expressions with calls or other side effects are left unchanged.

The optimizer folds direct `int` literal addition, subtraction, multiplication,
division, modulo, and shifts using exact integer arithmetic without converting
through floating point. Integer division truncates toward zero, and modulo
uses the matching remainder rule above. Division and modulo by zero remain
unfolded. Negative source operands are represented by unary expressions and
are not folded by this pass. Shift expressions fold only when both operands
are direct integer literals and the count is in the range 0 through 4096. The
4096 maximum is an optimizer resource guard to avoid excessive compile-time
allocation; it is not a MiniChain language limit, and larger shifts remain
unchanged in generated source. The lexer and AST retain integer literals as
Python integers, and the semantic analyzer assigns arithmetic an `int` result
when both operands are `int`. These exact folds follow the specified
arbitrary-precision integer behavior. No execution engine is provided here to
verify runtime behavior.

The optimizer also applies multiplication-to-shift strength reduction when
the multiplication has type `int`, one operand is a direct positive integer
power of two greater than 1, the other operand is an integer expression that
can be retained and evaluated once, and the resulting shift count is at most
4096. The dynamic expression is kept intact and occurs once in the output,
including when it contains a function call. The optimizer uses `OPT-016` and
`OPT-017` for factor 2, `OPT-018` and `OPT-019` for factor 4, and `OPT-020` and
`OPT-021` for factor 8 (right-side and left-side constants respectively).
`OPT-025` reports other supported powers of two.

This rewrite uses the specified arbitrary-precision integer behavior, under
which multiplication and left shift have the same mathematical result. The
generated program still requires an executor that follows this specification;
this repository does not include one. This rule does not enable
multiplication-to-shift rewriting for
floats, mixed types, non-powers of two, factors 0 or 1, negative factors, or
source-form negative integer literals in the dynamic expression, or shift
counts beyond the optimizer guard. The 4096 guard is a compile-time resource
limit only, not a language limit. The optimizer continues to defer
numeric comparisons, unary numeric negation, and floating-point folding. It
retains boolean constant folding and existing integer identity simplifications
where their type and evaluation guards allow. Division by one is also handled
by the existing identity rule. Zero multiplication is applied only when the
nonzero operand is a literal or identifier read, so calls and compound
expressions are not discarded.

The optimizer can also reduce integer division by a positive power of two to
arithmetic right shift (`value / 2**n` to `value >> n`), but only when a direct
`require` in the same proven control-flow path establishes that the same
integer parameter or local is nonnegative. It recognizes `value >= 0`,
`value > 0`, `0 <= value`, and `0 < value`. Assignments invalidate that fact;
facts established on only one side of a conditional or inside a loop do not
escape that path. State variables, compound numerators, function-call results,
variable divisors, divisors other than powers of two greater than one, and
shift counts above 4096 are not reduced. Direct literal divisions continue to
use constant folding first, and division by one keeps its existing identity
rule. Each applied rewrite is reported as `OPT-026`.

This restriction is necessary because division truncates toward zero while
arithmetic right shift rounds toward negative infinity: for example, `-7 / 2`
is `-3`, whereas `-7 >> 1` is `-4`. The rewrite therefore requires a proof of
nonnegativity. The optimizer treats a successful `require` as imposing its
condition on the continuing path; this is a source-level guard assumption,
not a runtime result verified by an execution engine.

The optimizer also propagates an exactly typed literal through later reads of
a local variable when the value is known on every path. Assignments invalidate
the value; nonconstant branches retain a value only when both paths agree, and
loop-written locals are treated as unknown after the loop. Propagation may
replace an identifier inside a numeric expression, but it does not fold the
numeric operation (for example, `x = 5; return x + 2;` may become
`return 5 + 2;`, not `return 7;`) unless that resulting expression consists
of supported integer literal arithmetic operands, in which case it folds to an
integer literal. Each replaced identifier is reported as `OPT-024`;
reports contain one entry for each actual rewrite occurrence. The optimizer
does not emit additional `OPT-001` or `OPT-002` statement summaries because
those duplicated the expression-level rewrite entries in the optimization
count. Boolean literals can still drive the existing `if` and `while`
simplifications.

The optimizer removes statements after `return` or `revert`, removes a
constant-false `while` loop only when its condition has no function call or
unknown expression, selects a boolean-literal `if` branch, and removes code
after an `if` only when both branches terminate. A `while (true)` loop is
retained, and the optimizer does not infer that statements after it are dead.
The language has no `for`, `break`, or `continue` syntax or corresponding AST
nodes, so loop-initializer and loop-transfer DCE are not implemented. Within a
loop body, the same return/revert and both-branches-terminate rules apply, but
their effects do not cross the loop boundary. `OPT-003`, `OPT-004`, and
`OPT-005` report branch or loop removal; `OPT-006` is emitted only when code
after a terminating statement is removed, so control-flow removals are not
also counted as generic dead-code removal. It does not remove local
declarations, parameters, state variables, or assignments based on unused
analysis. Instead it reports warning-only observations for unread locals,
parameters, state variables, and local values overwritten before a read.
State-variable warnings describe internal reads only; state is retained
because external visibility is not modeled. Dead-store warnings are
conservative around loops. Unused-analysis warnings do not remove statements;
the separate control-flow pass can still remove unreachable statements.

The implemented pass is a single source-order traversal with path-sensitive
literal tracking for straight-line code and conservative branch/loop joins.
Running it again on its own output is covered by regression tests. AST nodes
do not carry source locations, so optimization records identify rule and
transformation but cannot report a source line. These source-level
transformations have not been validated against a MiniChain execution engine
and do not establish runtime equivalence.

## 5. Compiler pipeline and generated-source validation

The Flask API and command-line entry point run lexical analysis, parsing,
semantic analysis, domain analysis, optimization, and code generation in that
order. Both parse the generated source again and rerun semantic analysis
before returning or writing it. The API returns `optimized_code` only when
that validation succeeds.

Domain findings are produced before optimization and describe the uploaded
source; the analyzer does not rerun domain rules on the optimized source. The
optimizer mutates its parsed AST. The API serializes the AST report before
optimization, then parses generated output into a separate AST for validation;
it does not retain a second in-memory copy of the original AST.
