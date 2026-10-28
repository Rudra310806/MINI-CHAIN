# MINI-CHAIN



## A Domain-Specific Smart Contract Compiler

MiniChain is a compiler-design project for a simplified contract-oriented language. It combines lexical analysis, parsing, AST construction, semantic analysis, domain-specific static analysis, AST optimization, code generation, and a Flask web interface.

> **Important:** Domain findings are heuristic source-pattern warnings, not proof that a contract is vulnerable or safe. Automatic repair supports selected rules only. Parsing and semantic validation of generated code do not prove runtime equivalence or security.

## Contents

- Features
- Compiler Pipeline
- Project Structure
- MiniChain Language Syntax
- Domain Analysis Rules
- Automatic Repair Coverage
- Optimizer Rules
- Run the Project
- Tests
- Limitations
- Team

## Features

- Custom `.mc` contract-oriented language.
- Lexer, parser, AST, and semantic analysis.
- Banking, Supply Chain, and Voting/Governance rule sets.
- Limited automatic repair with candidate re-analysis.
- AST-based optimizations and MiniChain code generation.
- Flask-based browser interface.
- Tests for compiler stages, domain rules, optimizer, and Flask endpoints.

## Compiler Pipeline

1. **Input:** MiniChain source and selected domain.
2. **Lexer (`compiler/lexer.py`):** Source text to tokens.
3. **Parser (`compiler/parser.py`):** Grammar validation and AST construction.
4. **AST (`compiler/ast_nodes.py`):** Structured program representation.
5. **Semantic analysis (`compiler/semantic.py`):** Supported declaration, reference, and type checks.
6. **Domain analysis (`compiler/domain_analyzer.py`):** Selected domain rules produce warnings.
7. **Automatic repair (`compiler/repair.py`):** Attempts supported fixes when requested.
8. **Optimization (`compiler/optimizer.py`):** Transforms the AST.
9. **Code generation (`compiler/codegen.py`):** AST to MiniChain source.
10. **Validation:** Generated code is parsed again and semantic analysis reruns before the Flask workflow returns it.

Domain findings refer to the submitted source; the analyzer does not rerun domain rules on optimized output.

## Project Structure

```text
MINI-CHAIN/
├── Bank.mc
├── Supplychain.mc
├── voting.mc
├── compiler/
│   ├── app.py
│   ├── ast_nodes.py
│   ├── codegen.py
│   ├── domain_analyzer.py
│   ├── lexer.py
│   ├── main.py
│   ├── optimizer.py
│   ├── parser.py
│   ├── repair.py
│   ├── semantic.py
│   ├── templates/
│   │   └── index.html
│   └── tests/
├── docs/
│   └── language-spec.md
├── optimized_outputs/
└── README.md
```

## MiniChain Language Syntax

### Basic contract

```text
contract Bank {
    state balance : int;

    function deposit(amount : int) {
        require(amount > 0);
        balance = balance + amount;
    }
}
```

### State declarations

Use `state name : type;`. Include the colon and semicolon.

```text
state balance : int;
state is_open : bool;
state status : string;
state owner : address;
```

Use only types supported by the current parser and semantic analyzer.

### Functions and parameters

Parameters use `name : type`, not C-style `type name`.

```text
function transfer(amount : int, recipient : address) {
    require(amount > 0);
}
```

Use braces for blocks and close parameter lists with `)`. Optional return types and statements must follow the grammar implemented in `compiler/parser.py`.

### Conditions, assignments, and strings

```text
require(amount > 0);
balance = balance + amount;
status = "registered";
```

Terminate supported statements with `;`. Put string values in quotes. Exponent notation for floating-point literals is not accepted by the current lexer. MiniChain is a teaching language and is not Solidity-compatible.

## Domain Analysis Rules

The analyzer applies the selected domain's rules to recognized function and identifier patterns. Equivalent logic with different names or control-flow shapes may not be recognized.

### Banking Rules

Checks run for functions named `deposit`, `withdraw`, and `transfer`.

| Rule | Trigger / meaning |
|---|---|
| `BANK-001` | `withdraw` lacks a recognized positive-amount condition (`amount > 0` or `0 < amount`). |
| `BANK-002` | `withdraw` lacks a recognized sufficient-balance condition (`amount <= balance` or `balance >= amount`). |
| `BANK-003` | `withdraw` lacks `balance = balance - amount` using its declared amount parameter. |
| `BANK-004` | `deposit` lacks a recognized positive-amount condition. |
| `BANK-005` | `deposit` lacks `balance = balance + amount`. |
| `BANK-006` | `transfer` lacks a recognized positive-amount condition. |
| `BANK-007` | `transfer` lacks a recognized sufficient-balance condition. |
| `BANK-008` | `transfer` lacks `balance = balance - amount`. |
| `BANK-009` | A matching top-level amount/balance `require` appears only after the first top-level balance write. |
| `BANK-010` | In a narrow nested-block case, a matching `require` follows a balance write in the same block without an equivalent enclosing/control-condition guard. |

Amount checks use a unique declared parameter whose name matches `amount` case-insensitively; comparisons use its exact spelling. These rules check patterns, not general branch dominance or transaction behavior.

### Supply Chain Rules

Recognized function names cover registration, dispatch, delivery, and ownership transfer. The analyzer recognizes selected status/state and owner names; custom identifiers may not trigger rules.

| Rule | Trigger / meaning |
|---|---|
| `SC-001` | Registration does not assign a recognized status field. |
| `SC-002` | Dispatch has no condition mentioning a recognized status field. |
| `SC-003` | Delivery has no condition checking a recognized status against `dispatched`, `shipped`, or `in_transit`. |
| `SC-004` | Ownership transfer has no condition mentioning a recognized owner field. |
| `SC-005` | Dispatch does not assign status `dispatched`, `shipped`, or `in_transit`. |
| `SC-006` | Delivery does not assign status `delivered`. |
| `SC-007` | Ownership transfer does not assign an owner field from an `address` parameter. |
| `SC-008` | Registration does not assign status `registered` or `created`. |
| `SC-009` | A recognized top-level dispatch/delivery status assignment appears before a `require` checking the expected prior status. |

These checks do not model product identity, multiple shipments, arbitrary custom lifecycle labels, or general control-flow dominance.

### Voting Rules

Checks run for recognized vote-submission function names.

| Rule | Trigger / meaning |
|---|---|
| `VOTE-001` | No condition mentions a recognized voting-period flag. |
| `VOTE-002` | No condition mentions a recognized voter-eligibility flag. |
| `VOTE-003` | No condition mentions a recognized duplicate-vote flag. |
| `VOTE-004` | No assignment targets a recognized vote-count or duplicate-vote identifier. |
| `VOTE-005` | A top-level `require(!flag)` or `require(flag == false)` for a duplicate-vote flag follows an assignment setting that same flag to `true`. |
| `VOTE-006` | A direct top-level `require` explicitly requires a recognized eligibility Boolean to be false. |
| `VOTE-007` | A direct top-level `require` explicitly requires a recognized voting-period Boolean to be false. |

These rules do not model voter identity, ballot choices, transaction atomicity, or the intended policy for a particular contract.

## Automatic Repair Coverage

Repair is intentionally limited and does not invent complete business logic.

| Rule(s) | Current behavior |
|---|---|
| `BANK-001`, `BANK-002`, `BANK-004`, `BANK-006`, `BANK-007` | Can insert selected amount/balance guards when required identifiers and preconditions are recognized. |
| `BANK-010` | Can reorder a narrowly matched adjacent guard/write pair in a supported nested block. |
| `SC-001` | Can insert a recognized initial status assignment. |
| `SC-002`, `SC-003` | Can insert selected status guards. |
| `SC-009` | Can reorder a narrowly matched adjacent prior-state guard and status transition. |
| `VOTE-001`, `VOTE-002`, `VOTE-003` | Can insert selected guards when recognized Boolean state declarations are available. |
| `BANK-003`, `BANK-005`, `BANK-008`, `BANK-009` | Not automatically repaired. |
| `SC-004`–`SC-008` | Not automatically repaired. |
| `VOTE-004`, `VOTE-005` | Not automatically repaired. |
| `VOTE-006`, `VOTE-007` | Manual review; intended policy cannot safely be inferred from a variable name. |

Repair candidates are reanalyzed. A candidate is accepted only if compiler validation succeeds and the targeted finding disappears. Unrelated warnings may remain.

## Optimizer Rules

The optimizer transforms the AST and records changes.

| Rule | Transformation |
|---|---|
| `OPT-003` | Select the `then` branch when an `if` condition is constant `true`. |
| `OPT-004` | Select the `else` branch when an `if` condition is constant `false`. |
| `OPT-005` | Remove a constant-false `while` loop. |
| `OPT-006` | Remove unreachable statements after `return`/`revert`, or after an `if` whose two branches terminate. |
| `OPT-007` | Fold supported literal operations, subject to implementation guards. |
| `OPT-008`, `OPT-009` | Integer `x + 0` and `0 + x` become `x`. |
| `OPT-010` | Integer `x - 0` becomes `x`. |
| `OPT-011`, `OPT-012` | Integer `x * 1` and `1 * x` become `x`. |
| `OPT-013`, `OPT-014` | Integer `x * 0` and `0 * x` become `0` when the other operand is a literal or identifier read. |
| `OPT-015` | `x / 1` becomes `x`; this is an identity rewrite, not division constant folding. |
| `OPT-016`–`OPT-021` | Selected multiplication-by-2/4/8 strength-reduction rules to left shifts, where enabled in the current implementation. |
| `OPT-024` | Replace an identifier with an exactly typed literal when its value is known on every path. |

The optimizer also handles selected unary/Boolean constants and conservative path-aware literal propagation. Check `compiler/optimizer.py` and `docs/language-spec.md` for the exact current guards and rule availability.

**Numeric semantics are not fully specified:** integer overflow, division/remainder, shifts, floating-point behavior, and conversions are not completely defined. Optimizations do not establish runtime equivalence for an unspecified execution model.

## Run the Project

From the repository root:

```powershell
cd compiler
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If a `requirements.txt` exists, install its dependencies:

```powershell
pip install -r requirements.txt
```

Start the Flask app:

```powershell
python app.py
```

Open the local address printed by Flask. If no `requirements.txt` is present, create one from the project's actual imports before expecting a clean setup on another machine.

The CLI entry point is `compiler/main.py`; consult its argument help or project documentation for the exact supported invocation.

## Tests

From the repository root:

```powershell
py -m pytest
```

The repository includes tests for CLI pipeline, domain analysis, Flask API, lexer/parser, optimizer, and semantic analysis. Tests require the appropriate project dependencies.

## Limitations

- Domain analysis uses recognized names and AST patterns; it is not formal verification.
- A warning is not necessarily a vulnerability, and no warning does not prove safety.
- Automatic repair only supports selected findings and may leave unrelated findings unresolved.
- Generated-code parsing and semantic checks do not prove security or behavioral equivalence.
- MiniChain is a teaching prototype, not a production smart-contract platform or a Solidity replacement.
- Runtime numeric semantics such as overflow, division/remainder, shifts, and floating-point behavior are not fully specified.

## Team

- **Rudra Pratap Singh** — `24BCT0337`
- **Abhishek Kumar Sharma** — `24BCI0084`
- **Nikesh J Raj** — `24BCI0059`
- **Saksham Ahuja** — `23BCE0731`

**Repository:** https://github.com/Rudra310806/MINI-CHAIN
