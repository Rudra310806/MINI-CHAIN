from ast_nodes import (
    Type,
    Block,
    VariableDeclaration,
    Assignment,
    IfStatement,
    WhileStatement,
    ReturnStatement,
    RequireStatement,
    RevertStatement,
    ExpressionStatement,
    Literal,
    Identifier,
    BinaryExpression,
    UnaryExpression,
    UpdateExpression,
    FunctionCall,
)

# Resource guard for compile-time shift evaluation. This is not a MiniChain
# language limit; larger literal shifts remain in the generated expression.
MAX_CONSTANT_SHIFT_COUNT = 4096


class OptimizationResult:
    """Stores information about one optimization."""

    def __init__(self, rule_id, message):
        self.rule_id = rule_id
        self.message = message

    def __str__(self):
        return f"[{self.rule_id}] {self.message}"


class Optimizer:
    """Performs conservative AST optimizations for MiniChain."""

    def __init__(self, program):
        self.program = program
        self.optimizations = []
        self.warnings = []
        self._type_env = {}
        self._function_return_types = {}
        self._local_variable_types = {}
        self._known_local_constants = {}
        self._known_nonnegative_identifiers = set()
        self._stable_integer_identifiers = set()

    def record(self, rule_id, message):
        self.optimizations.append(
            OptimizationResult(rule_id, message)
        )

    def optimize(self):
        self.optimizations = []
        self.warnings = []

        contract = self.program.contract

        self._function_return_types = {
            function.name: (
                function.return_type.name
                if function.return_type is not None
                else None
            )
            for function in contract.functions
        }

        state_types = {
            state.name: state.type.name
            for state in contract.states
        }

        for function in contract.functions:
            self._type_env = dict(state_types)
            self._local_variable_types = {}
            self._known_local_constants = {}
            self._known_nonnegative_identifiers = set()
            self._stable_integer_identifiers = {
                parameter.name
                for parameter in function.parameters
                if parameter.type.name == "int"
            }

            for parameter in function.parameters:
                self._type_env[parameter.name] = parameter.type.name

            function.body = self.optimize_block(function.body)

        self.detect_unused_variables(contract)

        return self.program

    # ---------------------------------------------------------
    # STATEMENT OPTIMIZATION
    # ---------------------------------------------------------

    def optimize_block(self, block):
        if block is None:
            return block

        optimized = []

        unreachable_tail_removed = False

        for statement_index, statement in enumerate(block.statements):

            if isinstance(statement, VariableDeclaration):
                if statement.initializer is not None:
                    statement.initializer = self.optimize_expression(
                        statement.initializer
                    )

                self._type_env[statement.name] = statement.type.name
                self._local_variable_types[statement.name] = statement.type.name
                self._known_nonnegative_identifiers.discard(statement.name)
                if statement.type.name == "int":
                    self._stable_integer_identifiers.add(statement.name)
                else:
                    self._stable_integer_identifiers.discard(statement.name)
                self._remember_literal(statement.name, statement.initializer)
                optimized.append(statement)

            elif isinstance(statement, Assignment):
                update = self.simplify_increment_assignment(statement)
                if update is not None:
                    self._known_local_constants.pop(statement.name, None)
                    self._known_nonnegative_identifiers.discard(statement.name)
                    optimized.append(
                        ExpressionStatement(expression=update)
                    )
                    continue

                statement.value = self.optimize_expression(
                    statement.value
                )

                if statement.name in self._local_variable_types:
                    self._remember_literal(statement.name, statement.value)

                # An assignment invalidates any earlier guard-derived fact.
                self._known_nonnegative_identifiers.discard(statement.name)
                optimized.append(statement)

            elif isinstance(statement, IfStatement):
                statement.condition = self.optimize_expression(
                    statement.condition
                )

                if (
                    isinstance(statement.condition, Literal)
                    and statement.condition.type.name == "bool"
                ):
                    if statement.condition.value is True:
                        statement.then_branch = self.optimize_block(
                            statement.then_branch
                        )
                        self.record(
                            "OPT-003",
                            "Removed unreachable else branch "
                            "from if(true)."
                        )

                        optimized.extend(
                            statement.then_branch.statements
                        )
                        if self.block_terminates(statement.then_branch):
                            unreachable_tail_removed = (
                                statement_index < len(block.statements) - 1
                            )
                            break

                    else:
                        if statement.else_branch is not None:
                            statement.else_branch = self.optimize_block(
                                statement.else_branch
                            )
                        self.record(
                            "OPT-004",
                            "Removed unreachable then branch "
                            "from if(false)."
                        )

                        if statement.else_branch is not None:
                            optimized.extend(
                                statement.else_branch.statements
                            )
                            if self.block_terminates(statement.else_branch):
                                unreachable_tail_removed = (
                                    statement_index < len(block.statements) - 1
                                )
                                break

                else:
                    incoming_constants = dict(self._known_local_constants)
                    incoming_nonnegative = set(
                        self._known_nonnegative_identifiers
                    )
                    incoming_stable_integers = set(
                        self._stable_integer_identifiers
                    )
                    statement.then_branch = self.optimize_block(
                        statement.then_branch
                    )
                    then_constants = dict(self._known_local_constants)
                    then_nonnegative = set(
                        self._known_nonnegative_identifiers
                    )

                    self._known_local_constants = dict(incoming_constants)
                    self._known_nonnegative_identifiers = set(
                        incoming_nonnegative
                    )
                    self._stable_integer_identifiers = set(
                        incoming_stable_integers
                    )
                    if statement.else_branch is not None:
                        statement.else_branch = self.optimize_block(
                            statement.else_branch
                        )
                    else_constants = dict(self._known_local_constants)
                    else_nonnegative = set(
                        self._known_nonnegative_identifiers
                    )

                    self._known_local_constants = {
                        name: value
                        for name, value in then_constants.items()
                        if name in else_constants
                        and value == else_constants[name]
                    }
                    # A fact survives a conditional only if it holds on
                    # every path and refers to a variable already in scope.
                    self._known_nonnegative_identifiers = (
                        then_nonnegative
                        & else_nonnegative
                        & incoming_stable_integers
                    )
                    self._stable_integer_identifiers = set(
                        incoming_stable_integers
                    )

                    optimized.append(statement)
                    if (
                        statement.else_branch is not None
                        and self.block_terminates(statement.then_branch)
                        and self.block_terminates(statement.else_branch)
                    ):
                        unreachable_tail_removed = (
                            statement_index < len(block.statements) - 1
                        )
                        break

            elif isinstance(statement, WhileStatement):
                condition_has_side_effects = (
                    self.expression_has_side_effects(
                        statement.condition
                    )
                )
                if not condition_has_side_effects:
                    statement.condition = self.optimize_expression(
                        statement.condition
                    )

                if (
                    not condition_has_side_effects
                    and
                    isinstance(statement.condition, Literal)
                    and statement.condition.type.name == "bool"
                    and statement.condition.value is False
                ):
                    self.record(
                        "OPT-005",
                        "Removed while loop with constant "
                        "false condition."
                    )

                else:
                    incoming_constants = dict(self._known_local_constants)
                    incoming_stable_integers = set(
                        self._stable_integer_identifiers
                    )
                    loop_modified = self.collect_block_local_writes(
                        statement.body
                    )
                    self._known_local_constants = {
                        name: value
                        for name, value in incoming_constants.items()
                        if name not in loop_modified
                    }
                    statement.body = self.optimize_block(
                        statement.body
                    )
                    # A loop may run zero or many times. Values written in
                    # the body are therefore unknown after the loop.
                    self._known_local_constants = {
                        name: value
                        for name, value in incoming_constants.items()
                        if name not in loop_modified
                    }
                    # The loop may run zero or many times. Do not export
                    # facts established in its body or retain facts across
                    # writes whose iteration count is unknown.
                    self._known_nonnegative_identifiers = set()
                    self._stable_integer_identifiers = set(
                        incoming_stable_integers
                    )
                    optimized.append(statement)

            elif isinstance(statement, ReturnStatement):
                if statement.value is not None:
                    statement.value = self.optimize_expression(
                        statement.value
                    )

                optimized.append(statement)

                # Statements after return cannot execute.
                unreachable_tail_removed = (
                    statement_index < len(block.statements) - 1
                )
                break

            elif isinstance(statement, RequireStatement):
                statement.condition = self.optimize_expression(
                    statement.condition
                )

                self.remember_nonnegative_require(statement.condition)
                optimized.append(statement)

            elif isinstance(statement, ExpressionStatement):
                statement.expression = self.optimize_expression(
                    statement.expression
                )

                optimized.append(statement)

            elif isinstance(statement, RevertStatement):
                optimized.append(statement)

                # Statements after revert cannot execute.
                unreachable_tail_removed = (
                    statement_index < len(block.statements) - 1
                )
                break

            else:
                optimized.append(statement)

        if unreachable_tail_removed:
            self.record(
                "OPT-006",
                "Removed code after a terminating statement."
            )

        block.statements = optimized
        return block

    def simplify_increment_assignment(self, statement):
        """Rewrite exact self-assignment by +/- one to a postfix update."""
        expression = statement.value
        if (
            not isinstance(expression, BinaryExpression)
            or expression.operator not in ("+", "-")
            or self._type_env.get(statement.name) != "int"
            or self.infer_type(expression) != "int"
        ):
            return None

        if (
            expression.operator == "+"
            and isinstance(expression.left, Identifier)
            and expression.left.name == statement.name
            and isinstance(expression.right, Literal)
            and expression.right.type.name == "int"
            and type(expression.right.value) is int
            and expression.right.value == 1
        ):
            operator = "++"
            source_expression = f"{statement.name} + 1"
        elif (
            expression.operator == "+"
            and isinstance(expression.left, Literal)
            and expression.left.type.name == "int"
            and type(expression.left.value) is int
            and expression.left.value == 1
            and isinstance(expression.right, Identifier)
            and expression.right.name == statement.name
        ):
            operator = "++"
            source_expression = f"1 + {statement.name}"
        elif (
            expression.operator == "-"
            and isinstance(expression.left, Identifier)
            and expression.left.name == statement.name
            and isinstance(expression.right, Literal)
            and expression.right.type.name == "int"
            and type(expression.right.value) is int
            and expression.right.value == 1
        ):
            operator = "--"
            source_expression = f"{statement.name} - 1"
        else:
            return None

        self.record(
            "OPT-027",
            f"Assignment simplification: {statement.name} = "
            f"{source_expression} -> {statement.name}{operator}.",
        )
        return UpdateExpression(
            operator=operator,
            operand=Identifier(name=statement.name),
            prefix=False,
        )

    # ---------------------------------------------------------
    # EXPRESSION OPTIMIZATION
    # ---------------------------------------------------------

    def optimize_expression(self, expression):

        update_targets = self.collect_updated_identifiers(expression)
        if update_targets:
            # Keep the whole expression intact: replacing a read beside an
            # update could change the value observed by the update.
            for name in update_targets:
                self._known_local_constants.pop(name, None)
                self._known_nonnegative_identifiers.discard(name)
            return expression

        if isinstance(expression, Identifier):
            known = self._known_local_constants.get(expression.name)
            if known is not None:
                self.record(
                    "OPT-024",
                    f"Propagated the known literal value of local "
                    f"'{expression.name}'."
                )
                return self.copy_literal(known)

            return expression

        if isinstance(expression, BinaryExpression):
            expression.left = self.optimize_expression(
                expression.left
            )

            expression.right = self.optimize_expression(
                expression.right
            )

            return self.optimize_binary_expression(expression)

        if isinstance(expression, UnaryExpression):
            expression.operand = self.optimize_expression(
                expression.operand
            )

            return self.optimize_unary_expression(expression)

        if isinstance(expression, FunctionCall):
            expression.arguments = [
                self.optimize_expression(argument)
                for argument in expression.arguments
            ]

            return expression

        return expression

    def _remember_literal(self, name, expression):
        """Track only direct, exactly typed literals for local variables."""
        if (
            isinstance(expression, Literal)
            and expression.type.name == self._local_variable_types.get(name)
        ):
            self._known_local_constants[name] = self.copy_literal(expression)
        else:
            self._known_local_constants.pop(name, None)

    @staticmethod
    def copy_literal(literal):
        return Literal(
            value=literal.value,
            type=Type(literal.type.name)
        )

    @staticmethod
    def block_terminates(block):
        if block is None or not block.statements:
            return False

        last = block.statements[-1]
        if isinstance(last, (ReturnStatement, RevertStatement)):
            return True

        return (
            isinstance(last, IfStatement)
            and last.else_branch is not None
            and Optimizer.block_terminates(last.then_branch)
            and Optimizer.block_terminates(last.else_branch)
        )

    @staticmethod
    def expression_has_side_effects(expression):
        """Conservatively identify effectful expressions before DCE."""
        if isinstance(expression, (FunctionCall, UpdateExpression)):
            return True

        if isinstance(expression, BinaryExpression):
            return (
                Optimizer.expression_has_side_effects(expression.left)
                or Optimizer.expression_has_side_effects(expression.right)
            )

        if isinstance(expression, UnaryExpression):
            return Optimizer.expression_has_side_effects(expression.operand)

        if isinstance(expression, (Literal, Identifier)):
            return False

        # An unrecognized expression is unsafe to discard or simplify.
        return True

    def collect_block_local_writes(self, block):
        """Collect locals assigned or declared in a possibly repeated loop."""
        written = set()
        if block is None:
            return written

        for statement in block.statements:
            if isinstance(statement, VariableDeclaration):
                written.add(statement.name)
                if statement.initializer is not None:
                    written.update(
                        self.collect_updated_identifiers(
                            statement.initializer
                        )
                    )
            elif isinstance(statement, Assignment):
                if statement.name in self._local_variable_types:
                    written.add(statement.name)
                written.update(
                    self.collect_updated_identifiers(statement.value)
                )
            elif isinstance(statement, IfStatement):
                written.update(
                    self.collect_updated_identifiers(statement.condition)
                )
                written.update(self.collect_block_local_writes(statement.then_branch))
                if statement.else_branch is not None:
                    written.update(self.collect_block_local_writes(statement.else_branch))
            elif isinstance(statement, WhileStatement):
                written.update(
                    self.collect_updated_identifiers(statement.condition)
                )
                written.update(self.collect_block_local_writes(statement.body))
            elif isinstance(statement, ReturnStatement):
                if statement.value is not None:
                    written.update(
                        self.collect_updated_identifiers(statement.value)
                    )
            elif isinstance(statement, RequireStatement):
                written.update(
                    self.collect_updated_identifiers(statement.condition)
                )
            elif isinstance(statement, ExpressionStatement):
                written.update(
                    self.collect_updated_identifiers(statement.expression)
                )

        return written & set(self._local_variable_types)

    @staticmethod
    def collect_updated_identifiers(expression):
        """Find variables written by update expressions in an expression."""
        if isinstance(expression, UpdateExpression):
            if isinstance(expression.operand, Identifier):
                return {expression.operand.name}
            return set()

        if isinstance(expression, BinaryExpression):
            return (
                Optimizer.collect_updated_identifiers(expression.left)
                | Optimizer.collect_updated_identifiers(expression.right)
            )

        if isinstance(expression, UnaryExpression):
            return Optimizer.collect_updated_identifiers(expression.operand)

        if isinstance(expression, FunctionCall):
            updated = set()
            for argument in expression.arguments:
                updated.update(
                    Optimizer.collect_updated_identifiers(argument)
                )
            return updated

        return set()

    # ---------------------------------------------------------
    # BINARY EXPRESSIONS
    # ---------------------------------------------------------

    def optimize_binary_expression(self, expression):
        left = expression.left
        right = expression.right
        operator = expression.operator

        # Constant folding
        if isinstance(left, Literal) and isinstance(right, Literal):
            result = self.evaluate_constants(
                left, operator, right
            )

            if result is not None:
                self.record(
                    "OPT-007",
                    f"Constant folding: {left.value!r} "
                    f"{operator} {right.value!r} "
                    f"-> {result.value!r}."
                )

                return result

        # These algebraic identities are only applied to expressions whose
        # operands are both known integers. Float identities can change
        # promotion, signed-zero, or special-value behavior.
        if (
            self.infer_type(left) != "int"
            or self.infer_type(right) != "int"
        ):
            return expression

        # x + 0 -> x
        if operator == "+":
            if self.is_number(right, 0):
                self.record(
                    "OPT-008",
                    "Algebraic simplification: x + 0 -> x."
                )
                return left

            if self.is_number(left, 0):
                self.record(
                    "OPT-009",
                    "Algebraic simplification: 0 + x -> x."
                )
                return right

        # x - 0 -> x
        elif operator == "-":
            if self.is_number(right, 0):
                self.record(
                    "OPT-010",
                    "Algebraic simplification: x - 0 -> x."
                )
                return left

        # Multiplication simplifications
        elif operator == "*":

            if self.is_number(right, 1):
                self.record(
                    "OPT-011",
                    "Algebraic simplification: x * 1 -> x."
                )
                return left

            if self.is_number(left, 1):
                self.record(
                    "OPT-012",
                    "Algebraic simplification: 1 * x -> x."
                )
                return right

            # x * 0 -> 0
            if self.is_number(right, 0):
                result_type = self.infer_type(left)

                if (
                    result_type in ("int", "float")
                    and self.is_safe_to_discard(left)
                ):
                    self.record(
                        "OPT-013",
                        "Algebraic simplification: x * 0 -> 0."
                    )

                    return Literal(
                        value=0.0 if result_type == "float" else 0,
                        type=Type(result_type)
                    )

            # 0 * x -> 0
            if self.is_number(left, 0):
                result_type = self.infer_type(right)

                if (
                    result_type in ("int", "float")
                    and self.is_safe_to_discard(right)
                ):
                    self.record(
                        "OPT-014",
                        "Algebraic simplification: 0 * x -> 0."
                    )

                    return Literal(
                        value=0.0 if result_type == "float" else 0,
                        type=Type(result_type)
                    )

            if self.infer_type(expression) == "int":
                reduced = self.reduce_integer_multiplication(expression)
                if reduced is not None:
                    return reduced

        # x / 1 -> x
        elif operator == "/":
            if self.is_number(right, 1):
                self.record(
                    "OPT-015",
                    "Algebraic simplification: x / 1 -> x."
                )
                return left

            reduced = self.reduce_integer_division(expression)
            if reduced is not None:
                return reduced

        return expression

    # ---------------------------------------------------------
    # UNARY EXPRESSIONS
    # ---------------------------------------------------------

    def optimize_unary_expression(self, expression):
        operand = expression.operand

        # !true -> false, !false -> true
        if (
            expression.operator == "!"
            and isinstance(operand, Literal)
            and operand.type.name == "bool"
        ):
            self.record(
                "OPT-023",
                "Constant folding applied to boolean negation."
            )

            return Literal(
                value=not operand.value,
                type=Type("bool")
            )

        return expression

    # ---------------------------------------------------------
    # CONSTANT EVALUATION
    # ---------------------------------------------------------

    def evaluate_constants(self, left, operator, right):
        # Fold exact integer arithmetic without converting through floats.
        # Integer division truncates toward zero; modulo uses the matching
        # quotient so its remainder has the dividend's sign. Shifts are
        # folded only for a bounded, nonnegative literal count. Zero divisors,
        # comparisons, bitwise ops, and floating-point operations remain
        # deferred.
        if (
            left.type.name == "int"
            and right.type.name == "int"
            and type(left.value) is int
            and type(right.value) is int
        ):
            if operator == "+":
                value = left.value + right.value
            elif operator == "-":
                value = left.value - right.value
            elif operator == "*":
                value = left.value * right.value
            elif operator in ("/", "%"):
                divisor = right.value
                if divisor == 0:
                    value = None
                else:
                    quotient = abs(left.value) // abs(divisor)
                    if (left.value < 0) != (divisor < 0):
                        quotient = -quotient

                    if operator == "/":
                        value = quotient
                    else:
                        value = left.value - quotient * divisor
            elif operator in ("<<", ">>"):
                shift_count = right.value
                if 0 <= shift_count <= MAX_CONSTANT_SHIFT_COUNT:
                    if operator == "<<":
                        value = left.value << shift_count
                    else:
                        value = left.value >> shift_count
                else:
                    value = None
            else:
                value = None

            if value is not None:
                # Code generation must be able to emit the exact integer
                # literal. Avoid folding a result Python cannot stringify
                # under its configured integer conversion limit.
                try:
                    str(value)
                except (ValueError, OverflowError):
                    return None

                return Literal(value=value, type=Type("int"))

        # Boolean literals have explicit values and remain safe to fold.
        if (
            left.type.name != "bool"
            or right.type.name != "bool"
            or not isinstance(left.value, bool)
            or not isinstance(right.value, bool)
        ):
            return None

        if operator == "&&":
            value = left.value and right.value
        elif operator == "||":
            value = left.value or right.value
        elif operator == "==":
            value = left.value == right.value
        elif operator == "!=":
            value = left.value != right.value
        else:
            return None

        return Literal(value=value, type=Type("bool"))

    # ---------------------------------------------------------
    # BASIC TYPE INFERENCE
    # ---------------------------------------------------------

    def infer_type(self, expression):

        if isinstance(expression, Literal):
            return expression.type.name

        if isinstance(expression, Identifier):
            return self._type_env.get(expression.name)

        if isinstance(expression, FunctionCall):
            return self._function_return_types.get(expression.name)

        if isinstance(expression, UpdateExpression):
            return "int"

        if isinstance(expression, UnaryExpression):
            if expression.operator == "!":
                return "bool"

            return self.infer_type(expression.operand)

        if isinstance(expression, BinaryExpression):

            if expression.operator in (
                "<", ">", "<=", ">=", "==", "!=", "&&", "||"
            ):
                return "bool"

            if expression.operator in ("<<", ">>", "&"):
                return "int"

            left_type = self.infer_type(expression.left)
            right_type = self.infer_type(expression.right)

            if "float" in (left_type, right_type):
                return "float"

            if left_type == "int" and right_type == "int":
                return "int"

        return None

    @staticmethod
    def is_number(expression, value):
        return (
            isinstance(expression, Literal)
            and expression.type.name in ("int", "float")
            and not isinstance(expression.value, bool)
            and expression.value == value
        )

    @staticmethod
    def is_safe_to_discard(expression):
        """Return whether evaluating this expression has no observable work.

        Zero multiplication removes evaluation of the nonzero operand. Keep
        that rewrite limited to literals and identifier reads; compound
        expressions may call functions or otherwise have observable behavior.
        """
        return isinstance(expression, (Literal, Identifier))

    def is_safe_integer_expression(self, expression):
        """Check that an int expression can be retained and evaluated once.

        This is not a purity test: calls are allowed because strength
        reduction preserves the original subtree exactly once. The constant
        operand is a side-effect-free integer literal.
        """
        if self.infer_type(expression) != "int":
            return False

        return self.is_single_evaluation_expression(expression)

    def is_single_evaluation_expression(self, expression):
        """Recognize expression forms whose original subtree can be reused."""
        if isinstance(expression, (Literal, Identifier)):
            return True

        if isinstance(expression, UnaryExpression):
            return self.is_single_evaluation_expression(expression.operand)

        if isinstance(expression, BinaryExpression):
            return (
                self.is_single_evaluation_expression(expression.left)
                and self.is_single_evaluation_expression(expression.right)
            )

        if isinstance(expression, FunctionCall):
            return all(
                self.is_single_evaluation_expression(argument)
                for argument in expression.arguments
            )

        if isinstance(expression, UpdateExpression):
            return False

        return False

    def reduce_integer_multiplication(self, expression):
        """Rewrite int multiplication by a guarded positive power of two."""
        if self.infer_type(expression) != "int":
            return None

        left = expression.left
        right = expression.right
        if (
            isinstance(right, Literal)
            and right.type.name == "int"
            and type(right.value) is int
        ):
            factor = right.value
            value_expression = left
            factor_is_left = False
        elif (
            isinstance(left, Literal)
            and left.type.name == "int"
            and type(left.value) is int
        ):
            factor = left.value
            value_expression = right
            factor_is_left = True
        else:
            return None

        if (
            factor <= 1
            or factor & (factor - 1)
            or not self.is_safe_integer_expression(value_expression)
            or self.contains_unary_negative_integer_literal(value_expression)
        ):
            return None

        shift_count = factor.bit_length() - 1
        if shift_count > MAX_CONSTANT_SHIFT_COUNT:
            return None

        reserved_rule_ids = {
            2: ("OPT-016", "OPT-017"),
            4: ("OPT-018", "OPT-019"),
            8: ("OPT-020", "OPT-021"),
        }
        if factor in reserved_rule_ids:
            rule_id = reserved_rule_ids[factor][int(factor_is_left)]
        else:
            # OPT-025 is the new generalized rule for powers beyond the
            # previously reserved factor-specific IDs.
            rule_id = "OPT-025"

        if factor_is_left:
            transformation = f"{factor} * x -> x << {shift_count}"
        else:
            transformation = f"x * {factor} -> x << {shift_count}"

        self.record(
            rule_id,
            f"Strength reduction: {transformation}.",
        )
        return BinaryExpression(
            left=value_expression,
            operator="<<",
            right=Literal(value=shift_count, type=Type("int")),
        )

    def remember_nonnegative_require(self, condition):
        """Remember simple integer facts established by a direct require."""
        if not isinstance(condition, BinaryExpression):
            return

        identifier = None
        operator = condition.operator
        zero = Literal(value=0, type=Type("int"))

        if (
            isinstance(condition.left, Identifier)
            and condition.right == zero
            and operator in (">=", ">")
        ):
            identifier = condition.left
        elif (
            isinstance(condition.right, Identifier)
            and condition.left == zero
            and operator in ("<=", "<")
        ):
            identifier = condition.right

        if (
            identifier is not None
            and identifier.name in self._stable_integer_identifiers
            and self._type_env.get(identifier.name) == "int"
        ):
            self._known_nonnegative_identifiers.add(identifier.name)

    def reduce_integer_division(self, expression):
        """Use arithmetic right shift only for a proven nonnegative local.

        A direct successful require guard is the only nonconstant proof used
        here. General range analysis and compound numerator reasoning are
        deliberately unsupported.
        """
        if self.infer_type(expression) != "int":
            return None

        numerator = expression.left
        divisor = expression.right
        if (
            not isinstance(numerator, Identifier)
            or numerator.name not in self._known_nonnegative_identifiers
            or numerator.name not in self._stable_integer_identifiers
            or self.infer_type(numerator) != "int"
            or not isinstance(divisor, Literal)
            or divisor.type.name != "int"
            or type(divisor.value) is not int
        ):
            return None

        factor = divisor.value
        if factor <= 1 or factor & (factor - 1):
            return None

        shift_count = factor.bit_length() - 1
        if shift_count > MAX_CONSTANT_SHIFT_COUNT:
            return None

        self.record(
            "OPT-026",
            f"Strength reduction: {numerator.name} / {factor} -> "
            f"{numerator.name} >> {shift_count} "
            "after a nonnegative require guard.",
        )
        return BinaryExpression(
            left=numerator,
            operator=">>",
            right=Literal(value=shift_count, type=Type("int")),
        )

    def contains_unary_negative_integer_literal(self, expression):
        """Avoid reducing expressions containing source-form negative ints."""
        if (
            isinstance(expression, UnaryExpression)
            and expression.operator == "-"
            and isinstance(expression.operand, Literal)
            and expression.operand.type.name == "int"
            and type(expression.operand.value) is int
        ):
            return True

        if isinstance(expression, UnaryExpression):
            return self.contains_unary_negative_integer_literal(
                expression.operand
            )

        if isinstance(expression, BinaryExpression):
            return (
                self.contains_unary_negative_integer_literal(expression.left)
                or self.contains_unary_negative_integer_literal(expression.right)
            )

        if isinstance(expression, FunctionCall):
            return any(
                self.contains_unary_negative_integer_literal(argument)
                for argument in expression.arguments
            )

        return False

    # ---------------------------------------------------------
    # UNUSED LOCAL VARIABLES
    # ---------------------------------------------------------

    def detect_unused_variables(self, contract):
        state_names = {state.name for state in contract.states}
        contract_reads = set()

        for function in contract.functions:
            declared = set()
            used = set()

            self.collect_variables(
                function.body,
                declared,
                used
            )

            for variable in sorted(declared - used):
                self.warnings.append(
                    f"Local variable '{variable}' in function "
                    f"'{function.name}' is never read; it was retained."
                )

            parameter_names = {parameter.name for parameter in function.parameters}
            for parameter in function.parameters:
                if parameter.name not in used:
                    self.warnings.append(
                        f"Parameter '{parameter.name}' in function "
                        f"'{function.name}' is never read; the function "
                        f"signature was retained."
                    )

            contract_reads.update(used & state_names)
            self.report_unread_local_assignments(
                function.body,
                declared | parameter_names,
                used,
                function.name,
            )

        for state in contract.states:
            if state.name not in contract_reads:
                self.warnings.append(
                    f"State variable '{state.name}' is not read by contract "
                    f"functions; it was retained because external visibility "
                    f"is not modeled."
                )

    def report_unread_local_assignments(
        self, block, local_names, ever_read, function_name
    ):
        """Report straight-line dead stores without deleting their statements.

        The analysis is conservative around loops. It reports values that are
        overwritten before a read, but leaves all assignments in the AST so
        potentially observable right-hand-side evaluation is preserved.
        """
        self._report_dead_stores_in_block(
            block, set(), local_names, ever_read, function_name
        )

    def _report_dead_stores_in_block(
        self, block, live_after, local_names, ever_read, function_name
    ):
        live = set(live_after)
        if block is None:
            return live

        for statement in reversed(block.statements):
            if isinstance(statement, Assignment):
                name = statement.name
                if (
                    name in local_names
                    and name in ever_read
                    and name not in live
                ):
                    self.warnings.append(
                        f"Assigned value of local '{name}' in function "
                        f"'{function_name}' is overwritten before a read; "
                        f"the assignment was retained."
                    )

                live.discard(name)
                self.collect_expression_variables(statement.value, live)

            elif isinstance(statement, VariableDeclaration):
                name = statement.name
                if (
                    statement.initializer is not None
                    and name in ever_read
                    and name not in live
                ):
                    self.warnings.append(
                        f"Initial value of local '{name}' in function "
                        f"'{function_name}' is overwritten before a read; "
                        f"the declaration was retained."
                    )

                live.discard(name)
                if statement.initializer is not None:
                    self.collect_expression_variables(
                        statement.initializer, live
                    )

            elif isinstance(statement, IfStatement):
                then_live = self._report_dead_stores_in_block(
                    statement.then_branch,
                    live,
                    local_names,
                    ever_read,
                    function_name,
                )
                else_live = (
                    self._report_dead_stores_in_block(
                        statement.else_branch,
                        live,
                        local_names,
                        ever_read,
                        function_name,
                    )
                    if statement.else_branch is not None
                    else set(live)
                )
                live = then_live | else_live
                self.collect_expression_variables(statement.condition, live)

            elif isinstance(statement, WhileStatement):
                # Loop writes can be consumed by a later iteration. Do not
                # diagnose stores inside the loop; retain reads conservatively.
                loop_declared = set()
                loop_reads = set()
                self.collect_variables(
                    statement.body, loop_declared, loop_reads
                )
                live.update(loop_reads)
                self.collect_expression_variables(statement.condition, live)

            elif isinstance(statement, ReturnStatement):
                if statement.value is not None:
                    self.collect_expression_variables(statement.value, live)

            elif isinstance(statement, RequireStatement):
                self.collect_expression_variables(statement.condition, live)

            elif isinstance(statement, ExpressionStatement):
                self.collect_expression_variables(statement.expression, live)

        return live

    def collect_variables(self, node, declared, used):

        if node is None:
            return

        if isinstance(node, Block):
            for statement in node.statements:
                self.collect_variables(
                    statement, declared, used
                )
            return

        if isinstance(node, VariableDeclaration):
            declared.add(node.name)

            if node.initializer is not None:
                self.collect_expression_variables(
                    node.initializer, used
                )
            return

        if isinstance(node, Assignment):
            self.collect_expression_variables(
                node.value, used
            )
            return

        if isinstance(node, IfStatement):
            self.collect_expression_variables(
                node.condition, used
            )

            self.collect_variables(
                node.then_branch, declared, used
            )

            if node.else_branch is not None:
                self.collect_variables(
                    node.else_branch, declared, used
                )
            return

        if isinstance(node, WhileStatement):
            self.collect_expression_variables(
                node.condition, used
            )

            self.collect_variables(
                node.body, declared, used
            )
            return

        if isinstance(node, ReturnStatement):
            if node.value is not None:
                self.collect_expression_variables(
                    node.value, used
                )
            return

        if isinstance(node, RequireStatement):
            self.collect_expression_variables(
                node.condition, used
            )
            return

        if isinstance(node, ExpressionStatement):
            self.collect_expression_variables(
                node.expression, used
            )

    def collect_expression_variables(self, expression, used):

        if isinstance(expression, Identifier):
            used.add(expression.name)
            return

        if isinstance(expression, BinaryExpression):
            self.collect_expression_variables(
                expression.left, used
            )

            self.collect_expression_variables(
                expression.right, used
            )
            return

        if isinstance(expression, UnaryExpression):
            self.collect_expression_variables(
                expression.operand, used
            )
            return

        if isinstance(expression, UpdateExpression):
            if isinstance(expression.operand, Identifier):
                used.add(expression.operand.name)
            return

        if isinstance(expression, FunctionCall):
            for argument in expression.arguments:
                self.collect_expression_variables(
                    argument, used
                )


if __name__ == "__main__":
    from lexer import Lexer
    from parser import Parser
    from codegen import CodeGenerator

    sample = """
    contract OptimizerTest {
        state balance : int;

        function calculate(amount : int) : int {
            int unused = 100;
            int doubled = amount * 2;
            int simplified = amount + 0;
            int constant = 3 * 4;

            if (true) {
                balance = balance + doubled;
            } else {
                balance = 0;
            }

            return simplified + constant;
        }
    }
    """

    parsed = Parser(Lexer(sample).tokenize()).parse()
    optimizer = Optimizer(parsed)
    optimized = optimizer.optimize()

    print("OPTIMIZATIONS")
    for item in optimizer.optimizations:
        print(item)

    print("\nWARNINGS")
    for warning in optimizer.warnings:
        print(warning)

    print("\nOPTIMIZED SOURCE")
    print(CodeGenerator().generate(optimized))
