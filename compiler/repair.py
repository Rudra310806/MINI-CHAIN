"""
Conservative source-level automatic repairs for MiniChain.

Only inserts checks/initializations when the relevant variable is already
declared, or moves a narrowly matched guard across its immediately adjacent
protected update. Every repaired contract must still be reviewed by a developer.
"""
import re

from ast_nodes import (
    Assignment,
    BinaryExpression,
    Block,
    Identifier,
    IfStatement,
    Literal,
    RequireStatement,
    WhileStatement,
)
from lexer import Lexer
from parser import Parser


UNSUPPORTED_REPAIR_RULES = {
    "VOTE-006": (
        "the contract does not declare an explicit policy for the intended "
        "eligibility value; identifier names alone do not establish it"
    ),
    "VOTE-007": (
        "the contract does not declare an explicit policy for the intended "
        "voting-period value; identifier names alone do not establish it"
    ),
}


def _parse_program(source):
    return Parser(Lexer(source).tokenize()).parse()


def _find_function(program, function_name):
    matches = [
        function
        for function in program.contract.functions
        if function.name == function_name
    ]
    return matches[0] if len(matches) == 1 else None


def _nested_blocks(block):
    for statement in block.statements:
        if isinstance(statement, IfStatement):
            yield statement.then_branch
            yield from _nested_blocks(statement.then_branch)
            if statement.else_branch is not None:
                yield statement.else_branch
                yield from _nested_blocks(statement.else_branch)
        elif isinstance(statement, WhileStatement):
            yield statement.body
            yield from _nested_blocks(statement.body)
        elif isinstance(statement, Block):
            yield statement
            yield from _nested_blocks(statement)


def _swap_unique_adjacent_lines(
    source, function_name, first_statement_pattern, second_statement_pattern
):
    """Swap two matching, same-indent, adjacent single-line statements."""
    span = _function_body_span(source, function_name)
    if span is None:
        return None

    opening, closing = span
    lines = source.splitlines(keepends=True)
    offsets = []
    offset = 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)

    first_pattern = re.compile(
        r"([ \t]*)" + first_statement_pattern + r";[ \t]*"
    )
    second_pattern = re.compile(
        r"([ \t]*)" + second_statement_pattern + r";[ \t]*"
    )
    matches = []

    for index in range(len(lines) - 1):
        first_start = offsets[index]
        second_end = offsets[index + 1] + len(lines[index + 1])
        if first_start <= opening or second_end > closing:
            continue

        first_text = lines[index].rstrip("\r\n")
        second_text = lines[index + 1].rstrip("\r\n")
        first_match = first_pattern.fullmatch(first_text)
        second_match = second_pattern.fullmatch(second_text)
        if (
            first_match is not None
            and second_match is not None
            and first_match.group(1) == second_match.group(1)
        ):
            matches.append(index)

    if len(matches) != 1:
        return None

    index = matches[0]
    candidate_lines = list(lines)
    candidate_lines[index], candidate_lines[index + 1] = (
        candidate_lines[index + 1],
        candidate_lines[index],
    )
    changes = [
        f"Moved `{lines[index + 1].strip()}` before `{lines[index].strip()}`."
    ]
    return "".join(candidate_lines), changes


def _simple_bank_guard(condition, amount_name):
    if not isinstance(condition, BinaryExpression):
        return None

    if (
        condition.operator == ">"
        and isinstance(condition.left, Identifier)
        and condition.left.name == amount_name
        and isinstance(condition.right, Literal)
        and condition.right.type.name == "int"
        and condition.right.value == 0
    ):
        amount = re.escape(amount_name)
        return "positive", rf"require\s*\(\s*{amount}\s*>\s*0\s*\)"

    if (
        condition.operator == "<="
        and isinstance(condition.left, Identifier)
        and condition.left.name == amount_name
        and isinstance(condition.right, Identifier)
        and condition.right.name == "balance"
    ):
        amount = re.escape(amount_name)
        return (
            "balance",
            rf"require\s*\(\s*{amount}\s*<=\s*balance\s*\)",
        )

    if (
        condition.operator == ">="
        and isinstance(condition.left, Identifier)
        and condition.left.name == "balance"
        and isinstance(condition.right, Identifier)
        and condition.right.name == amount_name
    ):
        amount = re.escape(amount_name)
        return (
            "balance",
            rf"require\s*\(\s*balance\s*>=\s*{amount}\s*\)",
        )

    return None


def _repair_bank_010(source, function_name):
    try:
        program = _parse_program(source)
    except Exception:
        return None

    function = _find_function(program, function_name)
    if function is None or function.name.lower() not in {
        "deposit", "withdraw", "transfer"
    }:
        return None

    amount_parameters = [
        parameter.name
        for parameter in function.parameters
        if parameter.name.casefold() == "amount"
    ]
    if len(amount_parameters) != 1:
        return None
    amount_name = amount_parameters[0]
    operation = function.name.lower()
    expected_operator = "+" if operation == "deposit" else "-"
    amount_pattern = re.escape(amount_name)
    assignment_pattern = (
        rf"balance\s*=\s*balance\s*{re.escape(expected_operator)}\s*"
        rf"{amount_pattern}"
    )

    candidates = []
    for block in _nested_blocks(function.body):
        for assignment, require in zip(block.statements, block.statements[1:]):
            if not isinstance(assignment, Assignment) or not isinstance(
                require, RequireStatement
            ):
                continue
            value = assignment.value
            if not (
                assignment.name == "balance"
                and isinstance(value, BinaryExpression)
                and value.operator == expected_operator
                and isinstance(value.left, Identifier)
                and value.left.name == "balance"
                and isinstance(value.right, Identifier)
                and value.right.name == amount_name
            ):
                continue

            guard = _simple_bank_guard(require.condition, amount_name)
            if guard is None or (guard[0] == "balance" and operation == "deposit"):
                continue
            candidates.append(guard[1])

    if len(candidates) != 1:
        return None

    moved = _swap_unique_adjacent_lines(
        source, function_name, assignment_pattern, candidates[0]
    )
    if moved is None:
        return None
    return moved


def _direct_prior_status_guard(condition, status_name, prior_values):
    if not isinstance(condition, BinaryExpression) or condition.operator != "==":
        return None

    for identifier, literal in (
        (condition.left, condition.right),
        (condition.right, condition.left),
    ):
        if (
            isinstance(identifier, Identifier)
            and identifier.name == status_name
            and isinstance(literal, Literal)
            and literal.type.name == "string"
            and isinstance(literal.value, str)
            and literal.value.casefold() in prior_values
        ):
            quote = rf"(?P<quote>['\"])\s*{re.escape(literal.value)}\s*(?P=quote)"
            return rf"require\s*\(\s*{re.escape(status_name)}\s*==\s*{quote}\s*\)"
    return None


def _repair_sc_009(source, function_name):
    try:
        program = _parse_program(source)
    except Exception:
        return None

    function = _find_function(program, function_name)
    if function is None:
        return None

    dispatch_names = {
        "dispatch", "dispatchproduct", "dispatchshipment", "ship",
        "shipproduct", "sendshipment",
    }
    delivery_names = {
        "deliver", "deliverproduct", "confirmdelivery", "receivedelivery",
        "markdelivered",
    }
    normalized_name = function.name.lower()
    if normalized_name in dispatch_names:
        prior_values = {"registered", "created"}
        next_values = {"dispatched", "shipped", "in_transit"}
    elif normalized_name in delivery_names:
        prior_values = {"dispatched", "shipped", "in_transit"}
        next_values = {"delivered"}
    else:
        return None

    recognized_states = {
        state.name
        for state in program.contract.states
        if state.type.name == "string"
        and state.name.casefold()
        in {"status", "state", "product_status", "shipment_status"}
    }
    candidates = []
    for assignment, require in zip(
        function.body.statements, function.body.statements[1:]
    ):
        if not isinstance(assignment, Assignment) or not isinstance(
            require, RequireStatement
        ):
            continue
        if not (
            assignment.name in recognized_states
            and isinstance(assignment.value, Literal)
            and assignment.value.type.name == "string"
            and isinstance(assignment.value.value, str)
            and assignment.value.value.casefold() in next_values
        ):
            continue

        guard_pattern = _direct_prior_status_guard(
            require.condition, assignment.name, prior_values
        )
        if guard_pattern is not None:
            next_value = re.escape(assignment.value.value)
            assignment_pattern = (
                rf"{re.escape(assignment.name)}\s*=\s*"
                rf"(?P<quote>['\"]){next_value}(?P=quote)"
            )
            candidates.append((assignment_pattern, guard_pattern))

    if len(candidates) != 1:
        return None

    assignment_pattern, guard_pattern = candidates[0]
    moved = _swap_unique_adjacent_lines(
        source, function_name, assignment_pattern, guard_pattern
    )
    if moved is None:
        return None
    return moved


def _function_body_span(source, function_name):
    """Return (opening_brace_index, closing_brace_index) for a named function."""
    match = re.search(
        r"\bfunction\s+" + re.escape(function_name) + r"\s*\([^)]*\)"
        r"(?:\s*:\s*[A-Za-z_]\w*)?\s*\{",
        source,
    )
    if not match:
        return None

    opening = source.find("{", match.start(), match.end())
    depth = 0
    in_string = None
    escaped = False

    for index in range(opening, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue

        if char in ("'", '"'):
            in_string = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return opening, index

    return None


def _declared_variables(source):
    """Map case-insensitive names to (source spelling, declared type)."""
    variables = {}
    # State declarations and function parameters/local declarations use name : type.
    for match in re.finditer(
        r"\bstate\s+([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)\s*;",
        source,
    ):
        name = match.group(1)
        variables[name.lower()] = (name, match.group(2).lower())

    for match in re.finditer(
        r"\b([A-Za-z_]\w*)\s*:\s*([A-Za-z_]\w*)",
        source,
    ):
        name = match.group(1)
        variables.setdefault(name.lower(), (name, match.group(2).lower()))

    for match in re.finditer(
        r"\b(?:int|float|bool|string|address)\s+([A-Za-z_]\w*)\b",
        source,
    ):
        name = match.group(1)
        variables.setdefault(name.lower(), (name, match.group(0).split()[0].lower()))

    return variables


def _function_parameters(source, function_name):
    match = re.search(
        r"\bfunction\s+" + re.escape(function_name) + r"\s*\(([^)]*)\)",
        source,
    )
    if not match:
        return {}
    parameters = {}
    for item in match.group(1).split(","):
        if item.strip():
            name = item.strip().split(":")[0].strip()
            parameters[name.lower()] = name
    return parameters


def _insert_after_opening_brace(source, function_name, statements):
    span = _function_body_span(source, function_name)
    if not span or not statements:
        return source, False

    opening, _ = span
    body_start = opening + 1
    # Avoid duplicating an identical guard/assignment already present in the body.
    body_end = _function_body_span(source, function_name)[1]
    body = source[body_start:body_end]
    missing = [statement for statement in statements if statement not in body]
    if not missing:
        return source, False

    newline = "\r\n" if "\r\n" in source else "\n"
    indentation_match = re.search(r"\n([ \t]*)\S", body)
    indent = indentation_match.group(1) if indentation_match else "        "
    insertion = newline + "".join(indent + item + newline for item in missing)
    return source[:body_start] + insertion + source[body_start:], True


def repair_source(source, domain, issues):
    """
    Return (repaired_source, applied, skipped).
    Repairs are limited to deterministic guard insertion and two narrowly
    matched adjacent-statement reorderings; the caller must revalidate them.
    """
    repaired = source
    applied = []
    skipped = []
    declarations = _declared_variables(source)

    for issue in issues:
        rule_id = issue.get("rule_id", "")
        function_name = issue.get("function")

        if rule_id == "BANK-010" and domain == "banking":
            moved = _repair_bank_010(repaired, function_name or "")
            if moved is None:
                skipped.append({
                    "rule_id": rule_id,
                    "reason": (
                        "Automatic repair was skipped for BANK-010: "
                        "the matching direct guard and balance update are not "
                        "a unique, adjacent pair in the same nested block; "
                        "no statement was moved."
                    ),
                })
            else:
                repaired, changes = moved
                applied.append({
                    "rule_id": rule_id,
                    "function": function_name,
                    "changes": changes,
                })
            continue

        if rule_id == "SC-009" and domain == "supply_chain":
            moved = _repair_sc_009(repaired, function_name or "")
            if moved is None:
                skipped.append({
                    "rule_id": rule_id,
                    "reason": (
                        "Automatic repair was skipped for SC-009: the "
                        "recognized direct prior-status require and matching "
                        "transition are not a unique adjacent top-level pair "
                        "with the same identifier; no statement was moved."
                    ),
                })
            else:
                repaired, changes = moved
                applied.append({
                    "rule_id": rule_id,
                    "function": function_name,
                    "changes": changes,
                })
            continue

        if rule_id in UNSUPPORTED_REPAIR_RULES:
            skipped.append({
                "rule_id": rule_id,
                "reason": (
                    f"Automatic repair is unsupported for {rule_id}: "
                    f"{UNSUPPORTED_REPAIR_RULES[rule_id]}."
                ),
            })
            continue

        if not function_name:
            # The analyzer normally supplies the function name. Do not guess.
            skipped.append({"rule_id": rule_id, "reason": "Could not identify the affected function."})
            continue

        parameters = _function_parameters(repaired, function_name)
        statements = []

        if domain == "banking":
            amount_name = parameters.get("amount")
            balance_declaration = declarations.get("balance")
            if rule_id in {"BANK-001", "BANK-004", "BANK-006"}:
                if amount_name:
                    statements = [f"require({amount_name} > 0);"]
            elif rule_id in {"BANK-002", "BANK-007"}:
                if amount_name and balance_declaration:
                    balance_name = balance_declaration[0]
                    statements = [f"require({amount_name} <= {balance_name});"]

        elif domain == "supply_chain":
            status_name = next(
                (declarations[name][0]
                 for name in ("status", "product_status", "shipment_status", "state")
                 if name in declarations and declarations[name][1] == "string"),
                None,
            )
            if rule_id == "SC-001" and status_name:
                statements = [f'{status_name} = "registered";']
            elif rule_id == "SC-002" and status_name:
                statements = [f'require({status_name} == "registered");']
            elif rule_id == "SC-003" and status_name:
                statements = [f'require({status_name} == "dispatched");']

        elif domain == "voting":
            if rule_id == "VOTE-001":
                name = next(
                    (declarations[n][0]
                     for n in ("is_voting_open", "voting_open", "is_active", "voting_active", "is_open", "active")
                     if n in declarations and declarations[n][1] == "bool"),
                    None,
                )
                if name:
                    statements = [f"require({name});"]
            elif rule_id == "VOTE-002":
                name = next(
                    (declarations[n][0]
                     for n in ("is_eligible", "eligible", "is_registered", "registered",
                               "is_authorized", "authorized", "valid_voter", "is_voter")
                     if n in declarations and declarations[n][1] == "bool"),
                    None,
                )
                if name:
                    statements = [f"require({name});"]
            elif rule_id == "VOTE-003":
                name = next(
                    (declarations[n][0]
                     for n in ("has_voted", "already_voted", "voted_before",
                               "voted", "vote_recorded", "has_cast_vote")
                     if n in declarations and declarations[n][1] == "bool"),
                    None,
                )
                if name:
                    statements = [f"require(!{name});"]

        if not statements:
            skipped.append({
                "rule_id": rule_id,
                "reason": "No safe automatic fix was identified from the declared variables and function signature.",
            })
            continue

        candidate, changed = _insert_after_opening_brace(repaired, function_name, statements)
        if changed:
            repaired = candidate
            applied.append({
                "rule_id": rule_id,
                "function": function_name,
                "changes": statements,
            })
        else:
            skipped.append({
                "rule_id": rule_id,
                "reason": "The proposed statement already exists or the function body could not be located.",
            })

    return repaired, applied, skipped
