from lexer import Lexer
from parser import Parser, ParserError

from ast_nodes import (
    Block,
    Assignment,
    IfStatement,
    WhileStatement,
    RequireStatement,
    Literal,
    Identifier,
    BinaryExpression,
    UnaryExpression,
)


class DomainIssue:
    """A domain-specific finding produced by a rule."""

    def __init__(self, rule_id, severity, message, function=None):
        self.rule_id = rule_id
        self.severity = severity
        self.message = message
        self.function = function

    def __str__(self):
        if self.function:
            return (
                f"[{self.severity}] {self.rule_id} "
                f"in {self.function}(): {self.message}"
            )
        return f"[{self.severity}] {self.rule_id}: {self.message}"


class DomainRule:
    """Base class for domain-specific analysis rules."""

    def check(self, contract):
        raise NotImplementedError


class BankingRule(DomainRule):
    """
    Basic static checks for deposit, withdraw, and transfer functions.

    These are heuristic source-level checks, not a formal proof of contract
    safety. A check is considered present when the expected comparison appears
    in a require/if/while condition or within a compound boolean expression.
    """

    def __init__(self):
        self.issues = []

    def check(self, contract):
        self.issues = []

        for function in contract.functions:
            name = function.name.lower()

            if name == "withdraw":
                self.check_withdraw(function)
            elif name == "deposit":
                self.check_deposit(function)
            elif name == "transfer":
                self.check_transfer(function)

        return self.issues

    def add_issue(self, rule_id, message, function):
        self.issues.append(
            DomainIssue(rule_id, "WARNING", message, function.name)
        )

    # --------------------------------------------------------
    # WITHDRAW
    # --------------------------------------------------------

    def check_withdraw(self, function):
        amount_name = self.amount_identifier(function)
        if not self.contains_condition(function.body, amount_name, ">", 0):
            self.add_issue(
                "BANK-001",
                "Withdrawal does not verify that the amount is greater than zero.",
                function,
            )

        has_balance_check = (
            self.contains_condition(function.body, amount_name, "<=", "balance")
            or self.contains_condition(function.body, "balance", ">=", amount_name)
        )

        if not has_balance_check:
            self.add_issue(
                "BANK-002",
                "Withdrawal does not verify that sufficient balance is available.",
                function,
            )

        if not self.has_balance_update(
            function.body, "withdraw", amount_name
        ):
            self.add_issue(
                "BANK-003",
                "Withdrawal does not appear to subtract the amount from balance.",
                function,
            )

        self.check_guard_order(function, "withdraw")

    # --------------------------------------------------------
    # DEPOSIT
    # --------------------------------------------------------

    def check_deposit(self, function):
        amount_name = self.amount_identifier(function)
        if not self.contains_condition(function.body, amount_name, ">", 0):
            self.add_issue(
                "BANK-004",
                "Deposit does not verify that the amount is greater than zero.",
                function,
            )

        if not self.has_balance_update(function.body, "deposit"):
            self.add_issue(
                "BANK-005",
                "Deposit does not appear to add the amount to balance.",
                function,
            )

        self.check_guard_order(function, "deposit")

    # --------------------------------------------------------
    # TRANSFER
    # --------------------------------------------------------

    def check_transfer(self, function):
        amount_name = self.amount_identifier(function)
        if not self.contains_condition(function.body, amount_name, ">", 0):
            self.add_issue(
                "BANK-006",
                "Transfer does not verify that the amount is greater than zero.",
                function,
            )

        has_balance_check = (
            self.contains_condition(function.body, amount_name, "<=", "balance")
            or self.contains_condition(function.body, "balance", ">=", amount_name)
        )

        if not has_balance_check:
            self.add_issue(
                "BANK-007",
                "Transfer does not verify that sufficient balance is available.",
                function,
            )

        if not self.has_balance_update(function.body, "transfer"):
            self.add_issue(
                "BANK-008",
                "Transfer does not appear to subtract the amount from balance.",
                function,
            )

        self.check_guard_order(function, "transfer")

    def check_guard_order(self, function, operation):
        """Warn when a recognized top-level require follows a balance write."""
        amount_parameters = [
            parameter.name
            for parameter in function.parameters
            if parameter.name.casefold() == "amount"
        ]
        if len(amount_parameters) != 1:
            return

        amount_name = amount_parameters[0]
        statements = function.body.statements

        def contains_balance_assignment(node):
            if isinstance(node, Block):
                return any(contains_balance_assignment(item) for item in node.statements)
            if isinstance(node, Assignment):
                return node.name == "balance"
            if isinstance(node, IfStatement):
                return (
                    contains_balance_assignment(node.then_branch)
                    or (
                        node.else_branch is not None
                        and contains_balance_assignment(node.else_branch)
                    )
                )
            if isinstance(node, WhileStatement):
                return contains_balance_assignment(node.body)
            return False

        mutation_indexes = [
            index
            for index, statement in enumerate(statements)
            if contains_balance_assignment(statement)
        ]
        if not mutation_indexes:
            return

        first_mutation = min(mutation_indexes)
        require_indexes = [
            (index, statement.condition)
            for index, statement in enumerate(statements)
            if isinstance(statement, RequireStatement)
        ]

        required_guards = [
            (amount_name, ">", 0),
        ]
        if operation in {"withdraw", "transfer"}:
            required_guards.append((amount_name, "<=", "balance"))

        late_guard = False
        for left_name, operator, right_value in required_guards:
            matches = [
                index
                for index, condition in require_indexes
                if self.expression_contains_condition(
                    condition, left_name, operator, right_value
                )
            ]

            if matches and not any(index < first_mutation for index in matches):
                late_guard = True
                break

        if late_guard:
            self.add_issue(
                "BANK-009",
                "A recognized amount or balance require appears after a balance update.",
                function,
            )

        if self.has_late_guard_in_nested_block(
            function.body, required_guards, inherited_guards=set(), nested=False
        ):
            self.add_issue(
                "BANK-010",
                "A recognized amount or balance require appears after a balance update inside a nested block.",
                function,
            )

    @staticmethod
    def amount_identifier(function):
        """Use the exact spelling of a unique amount parameter, if present."""
        names = [
            parameter.name
            for parameter in function.parameters
            if parameter.name.casefold() == "amount"
        ]
        if len(names) == 1:
            return names[0]
        if not names:
            # Preserve the prior convention for contracts that refer to a
            # state named amount instead of declaring an amount parameter.
            return "amount"
        return None

    def has_late_guard_in_nested_block(
        self, block, required_guards, inherited_guards, nested
    ):
        """Find a matching require after a balance write in a nested block.

        The check is intentionally syntactic and scoped to one Block. Guards
        in an enclosing block or the condition of the entering if/while are
        treated as preceding guards for the corresponding body.
        """
        seen_guards = set(inherited_guards)
        balance_write_seen = False

        for statement in block.statements:
            if isinstance(statement, RequireStatement):
                matching = {
                    guard_index
                    for guard_index, guard in enumerate(required_guards)
                    if self.expression_guarantees_condition(
                        statement.condition, *guard
                    )
                }
                if nested and balance_write_seen and matching - seen_guards:
                    return True
                seen_guards.update(matching)
                continue

            if isinstance(statement, IfStatement):
                condition_guards = {
                    guard_index
                    for guard_index, guard in enumerate(required_guards)
                    if self.expression_guarantees_condition(
                        statement.condition, *guard
                    )
                }
                if self.has_late_guard_in_nested_block(
                    statement.then_branch,
                    required_guards,
                    seen_guards | condition_guards,
                    nested=True,
                ):
                    return True
                if (
                    statement.else_branch is not None
                    and self.has_late_guard_in_nested_block(
                        statement.else_branch,
                        required_guards,
                        seen_guards,
                        nested=True,
                    )
                ):
                    return True
                if self.has_balance_assignment(statement):
                    balance_write_seen = True
                continue

            if isinstance(statement, WhileStatement):
                condition_guards = {
                    guard_index
                    for guard_index, guard in enumerate(required_guards)
                    if self.expression_guarantees_condition(
                        statement.condition, *guard
                    )
                }
                if self.has_late_guard_in_nested_block(
                    statement.body,
                    required_guards,
                    seen_guards | condition_guards,
                    nested=True,
                ):
                    return True
                if self.has_balance_assignment(statement):
                    balance_write_seen = True
                continue

            if isinstance(statement, Block):
                if self.has_late_guard_in_nested_block(
                    statement, required_guards, seen_guards, nested=True
                ):
                    return True
                if self.has_balance_assignment(statement):
                    balance_write_seen = True
                continue

            if self.has_balance_assignment(statement):
                balance_write_seen = True

        return False

    def expression_guarantees_condition(
        self, expression, left_name, operator, right_value
    ):
        """Match a guard atom guaranteed by a direct comparison or conjunction."""
        if not isinstance(expression, BinaryExpression):
            return False
        if expression.operator == "&&":
            return self.expression_guarantees_condition(
                expression.left, left_name, operator, right_value
            ) or self.expression_guarantees_condition(
                expression.right, left_name, operator, right_value
            )
        if expression.operator == "||":
            return False
        return self.expression_contains_condition(
            expression, left_name, operator, right_value
        )

    def has_balance_assignment(self, node):
        if isinstance(node, Block):
            return any(self.has_balance_assignment(item) for item in node.statements)
        if isinstance(node, Assignment):
            return node.name == "balance"
        if isinstance(node, IfStatement):
            return (
                self.has_balance_assignment(node.then_branch)
                or (
                    node.else_branch is not None
                    and self.has_balance_assignment(node.else_branch)
                )
            )
        if isinstance(node, WhileStatement):
            return self.has_balance_assignment(node.body)
        return False

    # --------------------------------------------------------
    # CONDITION SEARCH
    # --------------------------------------------------------

    def contains_condition(self, node, left_name, operator, right_value):
        """Search statement conditions recursively for a requested predicate."""
        if isinstance(node, Block):
            return any(
                self.contains_condition(statement, left_name, operator, right_value)
                for statement in node.statements
            )

        if isinstance(node, RequireStatement):
            return self.expression_contains_condition(
                node.condition, left_name, operator, right_value
            )

        if isinstance(node, IfStatement):
            if self.expression_contains_condition(
                node.condition, left_name, operator, right_value
            ):
                return True

            if self.contains_condition(
                node.then_branch, left_name, operator, right_value
            ):
                return True

            return (
                node.else_branch is not None
                and self.contains_condition(
                    node.else_branch, left_name, operator, right_value
                )
            )

        if isinstance(node, WhileStatement):
            if self.expression_contains_condition(
                node.condition, left_name, operator, right_value
            ):
                return True

            return self.contains_condition(
                node.body, left_name, operator, right_value
            )

        return False

    def expression_contains_condition(
        self, expression, left_name, operator, right_value
    ):
        """
        Find the comparison even when it is nested inside && or ||.
        Supports both `amount > 0` and `0 < amount` forms.
        """
        if not isinstance(expression, BinaryExpression):
            return False

        if expression.operator == operator:
            if self.matches_value(expression.left, left_name) and self.matches_value(
                expression.right, right_value
            ):
                return True

        # Normalize reversed forms for common comparisons:
        # 0 < amount means amount > 0.
        reverse_operator = {
            ">": "<",
            "<": ">",
            ">=": "<=",
            "<=": ">=",
            "==": "==",
            "!=": "!=",
        }.get(operator)

        if (
            reverse_operator == expression.operator
            and self.matches_value(expression.left, right_value)
            and self.matches_value(expression.right, left_name)
        ):
            return True

        return (
            self.expression_contains_condition(
                expression.left, left_name, operator, right_value
            )
            or self.expression_contains_condition(
                expression.right, left_name, operator, right_value
            )
        )

    @staticmethod
    def matches_value(node, expected):
        if isinstance(expected, str):
            return isinstance(node, Identifier) and node.name == expected

        if isinstance(expected, (int, float)):
            return (
                isinstance(node, Literal)
                and node.value == expected
                and not isinstance(node.value, bool)
            )

        return False

    # --------------------------------------------------------
    # BALANCE UPDATE SEARCH
    # --------------------------------------------------------

    def has_balance_update(self, node, operation, amount_name="amount"):
        """
        Check for a balance assignment with the expected arithmetic shape.

        deposit:  balance = balance + amount
        withdraw/transfer: balance = balance - amount

        Parentheses are represented by the AST structure, so they do not affect
        the check. Compound expressions such as balance = balance + amount + fee
        may be represented as nested BinaryExpression nodes and are checked
        recursively.
        """
        if isinstance(node, Block):
            return any(
                self.has_balance_update(statement, operation, amount_name)
                for statement in node.statements
            )

        if isinstance(node, Assignment):
            if node.name != "balance":
                return False

            expected_operator = "+" if operation == "deposit" else "-"
            return self.expression_has_balance_operation(
                node.value, expected_operator, amount_name
            )

        if isinstance(node, IfStatement):
            return (
                self.has_balance_update(
                    node.then_branch, operation, amount_name
                )
                or (
                    node.else_branch is not None
                    and self.has_balance_update(
                        node.else_branch, operation, amount_name
                    )
                )
            )

        if isinstance(node, WhileStatement):
            return self.has_balance_update(node.body, operation, amount_name)

        return False

    def expression_has_balance_operation(
        self, expression, operator, amount_name="amount"
    ):
        if not isinstance(expression, BinaryExpression):
            return False

        if expression.operator == operator:
            left_is_balance = (
                isinstance(expression.left, Identifier)
                and expression.left.name == "balance"
            )
            right_is_balance = (
                isinstance(expression.right, Identifier)
                and expression.right.name == "balance"
            )
            right_is_amount = (
                amount_name is not None
                and
                isinstance(expression.right, Identifier)
                and expression.right.name == amount_name
            )
            left_is_amount = (
                amount_name is not None
                and
                isinstance(expression.left, Identifier)
                and expression.left.name == amount_name
            )

            if operator == "+":
                if (left_is_balance and right_is_amount) or (
                    right_is_balance and left_is_amount
                ):
                    return True
            elif operator == "-" and left_is_balance and right_is_amount:
                return True

        return (
            self.expression_has_balance_operation(
                expression.left, operator, amount_name
            )
            or self.expression_has_balance_operation(
                expression.right, operator, amount_name
            )
        )


class SupplyChainRule(DomainRule):
    """
    Heuristic source-level checks for common supply-chain function patterns.

    The rules only inspect functions with recognized names. They do not prove
    contract security or understand runtime state transitions in every program.
    """

    STATUS_NAMES = {"status", "state", "product_status", "shipment_status"}
    OWNER_NAMES = {"owner", "current_owner", "previous_owner", "from_owner"}

    REGISTER_NAMES = {
        "register", "registerproduct", "createproduct", "addproduct"
    }
    DISPATCH_NAMES = {
        "dispatch", "dispatchproduct", "dispatchshipment", "ship",
        "shipproduct", "sendshipment"
    }
    DELIVERY_NAMES = {
        "deliver", "deliverproduct", "confirmdelivery", "receivedelivery",
        "markdelivered"
    }
    OWNERSHIP_NAMES = {
        "transferownership", "transfer_owner", "changeowner",
        "changeownership", "assignowner"
    }

    def __init__(self):
        self.issues = []
        self.status_state_names = set()
        self.owner_address_state_names = set()

    def check(self, contract):
        self.issues = []
        self.status_state_names = {
            state.name
            for state in contract.states
            if state.type.name == "string"
            and state.name.casefold() in self.STATUS_NAMES
        }
        self.owner_address_state_names = {
            state.name
            for state in contract.states
            if state.type.name == "address"
            and state.name.casefold() in self.OWNER_NAMES
        }

        for function in contract.functions:
            name = function.name.lower()

            if name in self.REGISTER_NAMES:
                self.check_registration(function)
            elif name in self.DISPATCH_NAMES:
                self.check_dispatch(function)
            elif name in self.DELIVERY_NAMES:
                self.check_delivery(function)
            elif name in self.OWNERSHIP_NAMES:
                self.check_ownership_transfer(function)

        return self.issues

    def add_issue(self, rule_id, message, function):
        self.issues.append(
            DomainIssue(rule_id, "WARNING", message, function.name)
        )

    def check_registration(self, function):
        if not self.has_assignment_to(function.body, self.STATUS_NAMES):
            self.add_issue(
                "SC-001",
                "Product registration does not appear to initialize a status/state variable.",
                function,
            )

        if not self.has_assignment_to_string(
            function.body, self.STATUS_NAMES, {"registered", "created"}
        ):
            self.add_issue(
                "SC-008",
                "Product registration does not appear to assign an initial registered/created status.",
                function,
            )

    def check_dispatch(self, function):
        if not self.has_state_condition(function.body):
            self.add_issue(
                "SC-002",
                "Dispatch does not appear to validate the product or shipment state before dispatch.",
                function,
            )

        if not self.has_assignment_to_string(
            function.body, self.STATUS_NAMES,
            {"dispatched", "shipped", "in_transit"},
        ):
            self.add_issue(
                "SC-005",
                "Dispatch does not appear to advance the status to a dispatched/shipped state.",
                function,
            )
        self.check_transition_guard_order(
            function,
            previous_values={"registered", "created"},
            next_values={"dispatched", "shipped", "in_transit"},
        )

    def check_delivery(self, function):
        if not self.has_expected_literal_condition(
            function.body, self.STATUS_NAMES, {"dispatched", "shipped", "in_transit"}
        ):
            self.add_issue(
                "SC-003",
                "Delivery does not appear to check that the product was dispatched or shipped first.",
                function,
            )

        if not self.has_assignment_to_string(
            function.body, self.STATUS_NAMES, {"delivered"}
        ):
            self.add_issue(
                "SC-006",
                "Delivery does not appear to mark the status as delivered.",
                function,
            )
        self.check_transition_guard_order(
            function,
            previous_values={"dispatched", "shipped", "in_transit"},
            next_values={"delivered"},
        )

    def check_transition_guard_order(self, function, previous_values, next_values):
        """Report a top-level recognized state guard that follows its transition."""
        statements = function.body.statements
        transition_indexes = [
            index
            for index, statement in enumerate(statements)
            if isinstance(statement, Assignment)
            and statement.name in self.status_state_names
            and isinstance(statement.value, Literal)
            and statement.value.type.name == "string"
            and isinstance(statement.value.value, str)
            and statement.value.value.casefold() in next_values
        ]
        guard_indexes = [
            index
            for index, statement in enumerate(statements)
            if isinstance(statement, RequireStatement)
            and self.expression_guarantees_expected_status(
                statement.condition, previous_values
            )
        ]

        if (
            transition_indexes
            and guard_indexes
            and min(guard_indexes) > min(transition_indexes)
        ):
            self.add_issue(
                "SC-009",
                "A recognized status transition occurs before its top-level prior-state require.",
                function,
            )

    def expression_guarantees_expected_status(self, expression, values):
        """Match status equality directly or as part of a conjunction."""
        if not isinstance(expression, BinaryExpression):
            return False
        if expression.operator == "&&":
            return (
                self.expression_guarantees_expected_status(expression.left, values)
                or self.expression_guarantees_expected_status(expression.right, values)
            )
        if expression.operator != "==":
            return False

        for identifier, literal in (
            (expression.left, expression.right),
            (expression.right, expression.left),
        ):
            if (
                isinstance(identifier, Identifier)
                and identifier.name.casefold() in self.STATUS_NAMES
                and isinstance(literal, Literal)
                and literal.type.name == "string"
                and isinstance(literal.value, str)
                and literal.value.casefold() in values
            ):
                return True
        return False

    def check_ownership_transfer(self, function):
        if not self.has_identifier_condition(function.body, self.OWNER_NAMES):
            self.add_issue(
                "SC-004",
                "Ownership transfer does not appear to validate the current or previous owner.",
                function,
            )

        address_parameters = {
            parameter.name
            for parameter in function.parameters
            if parameter.type.name == "address"
        }
        if not address_parameters or not self.has_assignment_from_parameter(
            function.body,
            self.owner_address_state_names,
            address_parameters,
        ):
            self.add_issue(
                "SC-007",
                "Ownership transfer does not appear to assign a recognized owner state from an address parameter.",
                function,
            )

    def has_assignment_to(self, node, names):
        if isinstance(node, Block):
            return any(self.has_assignment_to(item, names) for item in node.statements)

        if isinstance(node, Assignment):
            return node.name.lower() in names

        if isinstance(node, IfStatement):
            return (
                self.has_assignment_to(node.then_branch, names)
                or (
                    node.else_branch is not None
                    and self.has_assignment_to(node.else_branch, names)
                )
            )

        if isinstance(node, WhileStatement):
            return self.has_assignment_to(node.body, names)

        return False

    def has_assignment_to_string(self, node, names, values):
        if isinstance(node, Block):
            return any(
                self.has_assignment_to_string(statement, names, values)
                for statement in node.statements
            )

        if isinstance(node, Assignment):
            return (
                node.name.lower() in names
                and node.name in self.status_state_names
                and isinstance(node.value, Literal)
                and node.value.type.name == "string"
                and isinstance(node.value.value, str)
                and node.value.value.casefold() in values
            )

        if isinstance(node, IfStatement):
            return (
                self.has_assignment_to_string(node.then_branch, names, values)
                or (
                    node.else_branch is not None
                    and self.has_assignment_to_string(
                        node.else_branch, names, values
                    )
                )
            )

        if isinstance(node, WhileStatement):
            return self.has_assignment_to_string(node.body, names, values)

        return False

    def has_assignment_from_parameter(self, node, names, parameters):
        if isinstance(node, Block):
            return any(
                self.has_assignment_from_parameter(statement, names, parameters)
                for statement in node.statements
            )

        if isinstance(node, Assignment):
            return (
                node.name in names
                and isinstance(node.value, Identifier)
                and node.value.name in parameters
            )

        if isinstance(node, IfStatement):
            return (
                self.has_assignment_from_parameter(
                    node.then_branch, names, parameters
                )
                or (
                    node.else_branch is not None
                    and self.has_assignment_from_parameter(
                        node.else_branch, names, parameters
                    )
                )
            )

        if isinstance(node, WhileStatement):
            return self.has_assignment_from_parameter(
                node.body, names, parameters
            )

        return False

    def has_state_condition(self, node):
        return self.find_condition(
            node,
            lambda expression: self.expression_has_identifier(expression, self.STATUS_NAMES)
        )

    def has_identifier_condition(self, node, names):
        return self.find_condition(
            node,
            lambda expression: self.expression_has_identifier(expression, names)
        )

    def has_expected_literal_condition(self, node, identifier_names, expected_values):
        return self.find_condition(
            node,
            lambda expression: (
                self.expression_has_identifier(expression, identifier_names)
                and self.expression_has_literal(expression, expected_values)
            )
        )

    def find_condition(self, node, predicate):
        if isinstance(node, Block):
            return any(self.find_condition(item, predicate) for item in node.statements)

        if isinstance(node, RequireStatement):
            return predicate(node.condition)

        if isinstance(node, IfStatement):
            if predicate(node.condition):
                return True
            if self.find_condition(node.then_branch, predicate):
                return True
            return (
                node.else_branch is not None
                and self.find_condition(node.else_branch, predicate)
            )

        if isinstance(node, WhileStatement):
            return predicate(node.condition) or self.find_condition(node.body, predicate)

        return False

    def expression_has_identifier(self, expression, names):
        if isinstance(expression, Identifier) and expression.name.lower() in names:
            return True

        if isinstance(expression, BinaryExpression):
            return (
                self.expression_has_identifier(expression.left, names)
                or self.expression_has_identifier(expression.right, names)
            )

        return False

    def expression_has_literal(self, expression, expected_values):
        if isinstance(expression, Literal):
            return str(expression.value).strip('"').strip("'").lower() in expected_values

        if isinstance(expression, BinaryExpression):
            return (
                self.expression_has_literal(expression.left, expected_values)
                or self.expression_has_literal(expression.right, expected_values)
            )

        return False



class VotingRule(DomainRule):
    """
    Heuristic source-level checks for common voting-function patterns.

    These checks look for recognizable identifiers and assignments. They are
    not a formal proof that a voting contract prevents every attack.
    """

    VOTE_FUNCTION_NAMES = {
        "vote", "castvote", "submitvote", "castballot", "submitballot",
        "votefor", "cast_ballot", "submit_ballot",
    }
    PERIOD_NAMES = {
        "voting_open", "is_voting_open", "voting_active", "is_active",
        "voting_period", "start_time", "end_time", "deadline",
        "voting_deadline", "is_open", "active",
    }
    ELIGIBILITY_NAMES = {
        "eligible", "is_eligible", "registered", "is_registered",
        "authorized", "is_authorized", "valid_voter", "is_voter",
    }
    DUPLICATE_VOTE_NAMES = {
        "has_voted", "already_voted", "voted_before", "voted",
        "vote_recorded", "has_cast_vote",
    }
    VOTE_COUNT_NAMES = {
        "votes", "vote_count", "total_votes", "votes_cast",
        "totalvotes", "votecount",
    }

    def __init__(self):
        self.issues = []
        self.boolean_state_names = set()

    def check(self, contract):
        self.issues = []
        self.boolean_state_names = {
            state.name.casefold()
            for state in contract.states
            if state.type.name == "bool"
        }
        voting_functions = [
            function for function in contract.functions
            if function.name.lower() in self.VOTE_FUNCTION_NAMES
        ]

        for function in voting_functions:
            self.check_voting_function(function)

        return self.issues

    def add_issue(self, rule_id, message, function):
        self.issues.append(
            DomainIssue(rule_id, "WARNING", message, function.name)
        )

    def check_voting_function(self, function):
        if not self.has_condition_with_identifier(function.body, self.PERIOD_NAMES):
            self.add_issue(
                "VOTE-001",
                "Vote submission does not appear to validate the voting period.",
                function,
            )

        if not self.has_condition_with_identifier(function.body, self.ELIGIBILITY_NAMES):
            self.add_issue(
                "VOTE-002",
                "Vote submission does not appear to validate voter eligibility.",
                function,
            )

        if not self.has_condition_with_identifier(function.body, self.DUPLICATE_VOTE_NAMES):
            self.add_issue(
                "VOTE-003",
                "Vote submission does not appear to check whether the voter has already voted.",
                function,
            )

        if not self.has_assignment_to(function.body, self.VOTE_COUNT_NAMES | self.DUPLICATE_VOTE_NAMES):
            self.add_issue(
                "VOTE-004",
                "Vote submission does not appear to update a vote count or record the vote.",
                function,
            )

        if self.has_misordered_duplicate_vote_guard(function):
            self.add_issue(
                "VOTE-005",
                "A recognized duplicate-vote flag is set true before its direct not-voted require.",
                function,
            )

        boolean_names = self.boolean_state_names | {
            parameter.name.casefold()
            for parameter in function.parameters
            if parameter.type.name == "bool"
        }
        if self.has_direct_negative_flag_require(
            function, self.ELIGIBILITY_NAMES, boolean_names
        ):
            self.add_issue(
                "VOTE-006",
                "A direct require explicitly accepts a false recognized eligibility flag.",
                function,
            )

        if self.has_direct_negative_flag_require(
            function, self.PERIOD_NAMES, boolean_names
        ):
            self.add_issue(
                "VOTE-007",
                "A direct require explicitly accepts a false recognized voting-period flag.",
                function,
            )

    def has_direct_negative_flag_require(self, function, names, boolean_names):
        """Match only direct top-level require(!flag) / require(flag == false)."""
        for statement in function.body.statements:
            if not isinstance(statement, RequireStatement):
                continue
            condition = statement.condition

            if (
                isinstance(condition, UnaryExpression)
                and condition.operator == "!"
                and isinstance(condition.operand, Identifier)
                and condition.operand.name.casefold() in names
                and condition.operand.name.casefold() in boolean_names
            ):
                return True

            if (
                isinstance(condition, BinaryExpression)
                and condition.operator == "=="
            ):
                for identifier, literal in (
                    (condition.left, condition.right),
                    (condition.right, condition.left),
                ):
                    if (
                        isinstance(identifier, Identifier)
                        and identifier.name.casefold() in names
                        and identifier.name.casefold() in boolean_names
                        and isinstance(literal, Literal)
                        and literal.type.name == "bool"
                        and literal.value is False
                    ):
                        return True

        return False

    def has_misordered_duplicate_vote_guard(self, function):
        """Find a direct not-voted require that follows marking the same flag."""
        guard_indexes = {}
        mark_indexes = {}

        for index, statement in enumerate(function.body.statements):
            if isinstance(statement, RequireStatement):
                for name in self.not_voted_identifiers(statement.condition):
                    guard_indexes.setdefault(name, []).append(index)

            elif (
                isinstance(statement, Assignment)
                and statement.name.casefold() in self.DUPLICATE_VOTE_NAMES
                and isinstance(statement.value, Literal)
                and statement.value.type.name == "bool"
                and statement.value.value is True
            ):
                mark_indexes.setdefault(statement.name, []).append(index)

        for name, guards in guard_indexes.items():
            marks = mark_indexes.get(name, [])
            if marks and not any(
                guard_index < mark_index
                for guard_index in guards
                for mark_index in marks
            ):
                return True
        return False

    def not_voted_identifiers(self, expression):
        """Return exact flag spellings proven false by this narrow guard form."""
        if (
            isinstance(expression, UnaryExpression)
            and expression.operator == "!"
            and isinstance(expression.operand, Identifier)
            and expression.operand.name.casefold() in self.DUPLICATE_VOTE_NAMES
        ):
            return {expression.operand.name}

        if isinstance(expression, BinaryExpression):
            if expression.operator == "&&":
                return (
                    self.not_voted_identifiers(expression.left)
                    | self.not_voted_identifiers(expression.right)
                )

            if expression.operator == "==":
                if (
                    isinstance(expression.left, Identifier)
                    and expression.left.name.casefold()
                    in self.DUPLICATE_VOTE_NAMES
                    and isinstance(expression.right, Literal)
                    and expression.right.type.name == "bool"
                    and expression.right.value is False
                ):
                    return {expression.left.name}

                if (
                    isinstance(expression.right, Identifier)
                    and expression.right.name.casefold()
                    in self.DUPLICATE_VOTE_NAMES
                    and isinstance(expression.left, Literal)
                    and expression.left.type.name == "bool"
                    and expression.left.value is False
                ):
                    return {expression.right.name}

        return set()

    def has_condition_with_identifier(self, node, names):
        return self.find_condition(
            node,
            lambda expression: self.expression_has_identifier(expression, names),
        )

    def find_condition(self, node, predicate):
        if isinstance(node, Block):
            return any(self.find_condition(statement, predicate) for statement in node.statements)

        if isinstance(node, RequireStatement):
            return predicate(node.condition)

        if isinstance(node, IfStatement):
            if predicate(node.condition):
                return True
            if self.find_condition(node.then_branch, predicate):
                return True
            return (
                node.else_branch is not None
                and self.find_condition(node.else_branch, predicate)
            )

        if isinstance(node, WhileStatement):
            return predicate(node.condition) or self.find_condition(node.body, predicate)

        return False

    def expression_has_identifier(self, expression, names, _seen=None):
        """Find recognized identifiers anywhere in an expression AST.

        This deliberately handles unary nodes such as `!has_voted` without
        depending on a particular unary-expression class name.
        """
        if expression is None:
            return False

        if isinstance(expression, Identifier):
            return expression.name.lower() in names

        if _seen is None:
            _seen = set()
        obj_id = id(expression)
        if obj_id in _seen:
            return False
        _seen.add(obj_id)

        if isinstance(expression, BinaryExpression):
            return (
                self.expression_has_identifier(expression.left, names, _seen)
                or self.expression_has_identifier(expression.right, names, _seen)
            )

        # Other expression nodes (for example unary `!`) can contain child
        # expressions in attributes such as operand, expression, value, or
        # condition. Inspect AST fields recursively while avoiding primitives.
        if hasattr(expression, "__dict__"):
            for value in vars(expression).values():
                if isinstance(value, (list, tuple)):
                    for item in value:
                        if self.expression_has_identifier(item, names, _seen):
                            return True
                elif hasattr(value, "__dict__") or isinstance(value, Identifier):
                    if self.expression_has_identifier(value, names, _seen):
                        return True

        return False

    def has_assignment_to(self, node, names):
        if isinstance(node, Block):
            return any(self.has_assignment_to(statement, names) for statement in node.statements)

        if isinstance(node, Assignment):
            return node.name.lower() in names

        if isinstance(node, IfStatement):
            return (
                self.has_assignment_to(node.then_branch, names)
                or (
                    node.else_branch is not None
                    and self.has_assignment_to(node.else_branch, names)
                )
            )

        if isinstance(node, WhileStatement):
            return self.has_assignment_to(node.body, names)

        return False


class DomainAnalyzer:
    """Runs the rule set for the selected MiniChain application domain."""

    VALID_DOMAINS = {"banking", "supply_chain", "voting"}

    def __init__(self, program, domain):
        self.program = program
        self.domain = domain.lower().strip()
        self.rules = []
        self.issues = []
        self.load_rules()

    def load_rules(self):
        if self.domain not in self.VALID_DOMAINS:
            raise ValueError(f"Unknown domain: {self.domain}")

        self.rules = []

        if self.domain == "banking":
            self.rules.append(BankingRule())
        elif self.domain == "supply_chain":
            self.rules.append(SupplyChainRule())
        elif self.domain == "voting":
            self.rules.append(VotingRule())
    def analyze(self):
        self.issues = []
        contract = self.program.contract

        for rule in self.rules:
            self.issues.extend(rule.check(contract))

        return self.issues

    def print_report(self):
        print()
        print("=" * 60)
        print("DOMAIN ANALYSIS REPORT")
        print("=" * 60)
        print(f"Domain: {self.domain.upper()}")
        print()

        if not self.issues:
            print("No domain-specific issues detected.")
        else:
            print(f"Issues found: {len(self.issues)}")
            print()
            for issue in self.issues:
                print(f"  {issue}")


        print("=" * 60)


if __name__ == "__main__":
    source = """
    contract Bank {
        state balance : int;
        state owner : address;

        function deposit(amount : int) {
            require(amount > 0);
            balance = balance + amount;
        }

        function withdraw(amount : int) {
            require(amount > 0);
            require(amount <= balance);
            balance = balance - amount;
        }

        function getBalance() : int {
            return balance;
        }
    }
    """

    tokens = Lexer(source).tokenize()
    parser = Parser(tokens)

    try:
        program = parser.parse()
    except ParserError as error:
        print("Parser Error:")
        print(error)
        raise SystemExit(1)

    analyzer = DomainAnalyzer(program, "banking")
    analyzer.analyze()
    analyzer.print_report()
