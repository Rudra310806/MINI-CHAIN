import json
import math
from decimal import Decimal

from ast_nodes import (
    Program,
    Contract,
    StateDeclaration,
    FunctionDeclaration,
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


class CodeGenerationError(Exception):
    """Raised when the code generator encounters an unsupported AST node."""


class CodeGenerator:
    """
    Converts a MiniChain AST back into readable MiniChain source code.

    Binary expressions are parenthesized to preserve expression grouping.
    """

    def __init__(self, indent_size=4):
        self.indent_size = indent_size

    def generate(self, program):
        if not isinstance(program, Program):
            raise CodeGenerationError("Expected a Program AST node.")

        contract = program.contract
        lines = [f"contract {contract.name} {{"]

        for state in contract.states:
            lines.append(self.generate_state(state))

        if contract.states and contract.functions:
            lines.append("")

        for index, function in enumerate(contract.functions):
            lines.extend(self.generate_function(function))
            if index != len(contract.functions) - 1:
                lines.append("")

        lines.append("}")
        return "\n".join(lines) + "\n"

    def generate_state(self, state):
        return (
            f"{self.indent(1)}state {state.name} : "
            f"{self.type_name(state.type)};"
        )

    def generate_function(self, function):
        parameters = ", ".join(
            f"{parameter.name} : {self.type_name(parameter.type)}"
            for parameter in function.parameters
        )

        signature = (
            f"{self.indent(1)}function {function.name}({parameters})"
        )

        if function.return_type is not None:
            signature += f" : {self.type_name(function.return_type)}"

        lines = [signature + " {"]
        lines.extend(self.generate_block_contents(function.body, 2))
        lines.append(f"{self.indent(1)}}}")
        return lines

    def generate_block_contents(self, block, depth):
        lines = []

        for statement in block.statements:
            lines.extend(self.generate_statement(statement, depth))

        return lines

    def generate_statement(self, statement, depth):
        prefix = self.indent(depth)

        if isinstance(statement, VariableDeclaration):
            result = f"{prefix}{self.type_name(statement.type)} {statement.name}"

            if statement.initializer is not None:
                result += f" = {self.generate_expression(statement.initializer)}"

            return [result + ";"]

        if isinstance(statement, Assignment):
            return [
                f"{prefix}{statement.name} = "
                f"{self.generate_expression(statement.value)};"
            ]

        if isinstance(statement, IfStatement):
            lines = [
                f"{prefix}if ({self.generate_expression(statement.condition)}) {{"
            ]
            lines.extend(
                self.generate_block_contents(statement.then_branch, depth + 1)
            )
            lines.append(f"{prefix}}}")

            if statement.else_branch is not None:
                lines[-1] += " else {"
                lines.extend(
                    self.generate_block_contents(
                        statement.else_branch, depth + 1
                    )
                )
                lines.append(f"{prefix}}}")

            return lines

        if isinstance(statement, WhileStatement):
            lines = [
                f"{prefix}while ({self.generate_expression(statement.condition)}) {{"
            ]
            lines.extend(
                self.generate_block_contents(statement.body, depth + 1)
            )
            lines.append(f"{prefix}}}")
            return lines

        if isinstance(statement, ReturnStatement):
            if statement.value is None:
                return [f"{prefix}return;"]

            return [
                f"{prefix}return {self.generate_expression(statement.value)};"
            ]

        if isinstance(statement, RequireStatement):
            return [
                f"{prefix}require("
                f"{self.generate_expression(statement.condition)});"
            ]

        if isinstance(statement, RevertStatement):
            return [f"{prefix}revert();"]

        if isinstance(statement, ExpressionStatement):
            return [
                f"{prefix}{self.generate_expression(statement.expression)};"
            ]

        raise CodeGenerationError(
            f"Unsupported statement node: {type(statement).__name__}"
        )

    def generate_expression(self, expression):
        if isinstance(expression, Literal):
            if expression.type.name == "bool":
                return "true" if expression.value else "false"

            if expression.type.name == "string":
                return json.dumps(expression.value, ensure_ascii=False)

            if expression.type.name == "float":
                return self.generate_float_literal(expression.value)

            return repr(expression.value)

        if isinstance(expression, Identifier):
            return expression.name

        if isinstance(expression, BinaryExpression):
            left = self.generate_expression(expression.left)
            right = self.generate_expression(expression.right)
            return f"({left} {expression.operator} {right})"

        if isinstance(expression, UnaryExpression):
            operand = self.generate_expression(expression.operand)

            if expression.operator.isalpha():
                return f"{expression.operator} {operand}"

            return f"({expression.operator}{operand})"

        if isinstance(expression, UpdateExpression):
            operand = self.generate_expression(expression.operand)
            if expression.prefix:
                return f"{expression.operator}{operand}"
            return f"{operand}{expression.operator}"

        if isinstance(expression, FunctionCall):
            arguments = ", ".join(
                self.generate_expression(argument)
                for argument in expression.arguments
            )
            return f"{expression.name}({arguments})"

        raise CodeGenerationError(
            f"Unsupported expression node: {type(expression).__name__}"
        )

    @staticmethod
    def generate_float_literal(value):
        try:
            numeric_value = float(value)
        except (TypeError, ValueError, OverflowError) as error:
            raise CodeGenerationError(
                f"Cannot generate float literal from {value!r}."
            ) from error

        if not math.isfinite(numeric_value):
            raise CodeGenerationError(
                "MiniChain source does not support non-finite float literals."
            )

        # The lexer accepts decimal notation but not exponent notation.
        # Expand Python's exponent form without changing its round-trip value.
        literal = repr(numeric_value)
        if "e" in literal.lower():
            literal = format(Decimal(literal), "f")

        # Preserve the float type when the expanded value is an integer.
        if "." not in literal:
            literal += ".0"

        return literal

    def type_name(self, type_node):
        return type_node.name

    def indent(self, depth):
        return " " * (self.indent_size * depth)


if __name__ == "__main__":
    from lexer import Lexer
    from parser import Parser

    example = """
    contract Example {
        state balance : int;

        function deposit(amount : int) {
            require(amount > 0);
            balance = balance + amount;
        }

        function getBalance() : int {
            return balance;
        }
    }
    """

    parsed_program = Parser(Lexer(example).tokenize()).parse()
    print(CodeGenerator().generate(parsed_program))
