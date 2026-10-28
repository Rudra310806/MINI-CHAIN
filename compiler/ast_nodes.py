from dataclasses import dataclass, field
from typing import List, Optional


# ============================================================
# BASE AST NODE
# ============================================================

@dataclass
class ASTNode:
    """
    Base class for every node in the MiniChain AST.
    """
    pass


# ============================================================
# PROGRAM STRUCTURE
# ============================================================

@dataclass
class Program(ASTNode):
    """
    Represents the complete MiniChain program.
    """

    contract: "Contract"


@dataclass
class Contract(ASTNode):
    """
    Represents a MiniChain contract.

    Example:

        contract Bank {
            ...
        }
    """

    name: str
    states: List["StateDeclaration"] = field(default_factory=list)
    functions: List["FunctionDeclaration"] = field(default_factory=list)


# ============================================================
# TYPES
# ============================================================

@dataclass
class Type(ASTNode):
    """
    Represents a MiniChain data type.

    Examples:
        int
        float
        bool
        string
        address
    """

    name: str


# ============================================================
# STATE VARIABLES
# ============================================================

@dataclass
class StateDeclaration(ASTNode):
    """
    Represents a contract-level state variable.

    Example:

        state balance : int;
    """

    name: str
    type: Type


# ============================================================
# FUNCTION DECLARATION
# ============================================================

@dataclass
class Parameter(ASTNode):
    """
    Represents a function parameter.

    Example:

        amount : int
    """

    name: str
    type: Type


@dataclass
class FunctionDeclaration(ASTNode):
    """
    Represents a function.

    Example:

        function deposit(amount : int) {
            ...
        }
    """

    name: str
    parameters: List[Parameter] = field(default_factory=list)
    return_type: Optional[Type] = None
    body: "Block" = None


# ============================================================
# STATEMENTS
# ============================================================

@dataclass
class Statement(ASTNode):
    """
    Base class for all statements.
    """
    pass


@dataclass
class Block(Statement):
    """
    Represents a block of statements.

    Example:

        {
            statement1;
            statement2;
        }
    """

    statements: List[Statement] = field(default_factory=list)


@dataclass
class VariableDeclaration(Statement):
    """
    Represents a local variable declaration.

    Example:

        int remaining;
    """

    name: str
    type: Type
    initializer: Optional["Expression"] = None


@dataclass
class Assignment(Statement):
    """
    Represents an assignment.

    Example:

        balance = balance + amount;
    """

    name: str
    value: "Expression"


@dataclass
class IfStatement(Statement):
    """
    Represents an if/else statement.

    Example:

        if (amount > balance) {
            revert();
        }
        else {
            ...
        }
    """

    condition: "Expression"
    then_branch: Block
    else_branch: Optional[Block] = None


@dataclass
class WhileStatement(Statement):
    """
    Represents a while loop.

    Example:

        while (amount > 0) {
            amount = amount - 1;
        }
    """

    condition: "Expression"
    body: Block


@dataclass
class ReturnStatement(Statement):
    """
    Represents a return statement.

    Example:

        return balance;
    """

    value: Optional["Expression"] = None


@dataclass
class RequireStatement(Statement):
    """
    Represents a require statement.

    Example:

        require(amount > 0);
    """

    condition: "Expression"


@dataclass
class RevertStatement(Statement):
    """
    Represents a revert statement.

    Example:

        revert();
    """

    pass


@dataclass
class ExpressionStatement(Statement):
    """
    Represents an expression used as a statement.

    Example:

        deposit(amount);
    """

    expression: "Expression"


# ============================================================
# EXPRESSIONS
# ============================================================

@dataclass
class Expression(ASTNode):
    """
    Base class for all expressions.
    """
    pass


@dataclass
class Literal(Expression):
    """
    Represents a literal value.

    Examples:

        100
        45.5
        true
        "hello"
    """

    value: object
    type: Type


@dataclass
class Identifier(Expression):
    """
    Represents a variable or identifier.

    Example:

        balance
        amount
        owner
    """

    name: str


@dataclass
class BinaryExpression(Expression):
    """
    Represents a binary operation.

    Example:

        balance + amount

    Structure:

        left  -> balance
        op    -> +
        right -> amount
    """

    left: Expression
    operator: str
    right: Expression


@dataclass
class UnaryExpression(Expression):
    """
    Represents a unary operation.

    Example:

        !active
        -amount
    """

    operator: str
    operand: Expression


@dataclass
class UpdateExpression(Expression):
    """Increment or decrement of a writable integer identifier."""

    operator: str
    operand: "Identifier"
    prefix: bool


@dataclass
class FunctionCall(Expression):
    """
    Represents a function call.

    Example:

        deposit(amount);

    or:

        transfer(to, amount);
    """

    name: str
    arguments: List[Expression] = field(default_factory=list)


# ============================================================
# AST PRINTER
# ============================================================

class ASTPrinter:
    """
    Converts the AST into a readable tree representation.

    This is useful for testing the parser.
    """

    def print(self, node, indent=0):

        spacing = "  " * indent

        if node is None:
            return

        # ----------------------------------------------------
        # Program
        # ----------------------------------------------------

        if isinstance(node, Program):

            print(f"{spacing}Program")

            self.print(
                node.contract,
                indent + 1
            )

        # ----------------------------------------------------
        # Contract
        # ----------------------------------------------------

        elif isinstance(node, Contract):

            print(
                f"{spacing}Contract: {node.name}"
            )

            for state in node.states:
                self.print(
                    state,
                    indent + 1
                )

            for function in node.functions:
                self.print(
                    function,
                    indent + 1
                )

        # ----------------------------------------------------
        # State Declaration
        # ----------------------------------------------------

        elif isinstance(node, StateDeclaration):

            print(
                f"{spacing}State: "
                f"{node.name} : {node.type.name}"
            )

        # ----------------------------------------------------
        # Function Declaration
        # ----------------------------------------------------

        elif isinstance(node, FunctionDeclaration):

            return_type = (
                node.return_type.name
                if node.return_type
                else "void"
            )

            print(
                f"{spacing}Function: "
                f"{node.name} -> {return_type}"
            )

            for parameter in node.parameters:

                print(
                    f"{spacing}  Parameter: "
                    f"{parameter.name} : "
                    f"{parameter.type.name}"
                )

            self.print(
                node.body,
                indent + 1
            )

        # ----------------------------------------------------
        # Parameter
        # ----------------------------------------------------

        elif isinstance(node, Parameter):

            print(
                f"{spacing}Parameter: "
                f"{node.name} : {node.type.name}"
            )

        # ----------------------------------------------------
        # Block
        # ----------------------------------------------------

        elif isinstance(node, Block):

            print(f"{spacing}Block")

            for statement in node.statements:

                self.print(
                    statement,
                    indent + 1
                )

        # ----------------------------------------------------
        # Variable Declaration
        # ----------------------------------------------------

        elif isinstance(node, VariableDeclaration):

            print(
                f"{spacing}Variable: "
                f"{node.name} : "
                f"{node.type.name}"
            )

            if node.initializer:

                print(
                    f"{spacing}  Initializer:"
                )

                self.print(
                    node.initializer,
                    indent + 2
                )

        # ----------------------------------------------------
        # Assignment
        # ----------------------------------------------------

        elif isinstance(node, Assignment):

            print(
                f"{spacing}Assignment: "
                f"{node.name}"
            )

            self.print(
                node.value,
                indent + 1
            )

        # ----------------------------------------------------
        # If Statement
        # ----------------------------------------------------

        elif isinstance(node, IfStatement):

            print(
                f"{spacing}If"
            )

            print(
                f"{spacing}  Condition:"
            )

            self.print(
                node.condition,
                indent + 2
            )

            print(
                f"{spacing}  Then:"
            )

            self.print(
                node.then_branch,
                indent + 2
            )

            if node.else_branch:

                print(
                    f"{spacing}  Else:"
                )

                self.print(
                    node.else_branch,
                    indent + 2
                )

        # ----------------------------------------------------
        # While Statement
        # ----------------------------------------------------

        elif isinstance(node, WhileStatement):

            print(
                f"{spacing}While"
            )

            print(
                f"{spacing}  Condition:"
            )

            self.print(
                node.condition,
                indent + 2
            )

            print(
                f"{spacing}  Body:"
            )

            self.print(
                node.body,
                indent + 2
            )

        # ----------------------------------------------------
        # Return Statement
        # ----------------------------------------------------

        elif isinstance(node, ReturnStatement):

            print(
                f"{spacing}Return"
            )

            if node.value:

                self.print(
                    node.value,
                    indent + 1
                )

        # ----------------------------------------------------
        # Require Statement
        # ----------------------------------------------------

        elif isinstance(node, RequireStatement):

            print(
                f"{spacing}Require"
            )

            self.print(
                node.condition,
                indent + 1
            )

        # ----------------------------------------------------
        # Revert Statement
        # ----------------------------------------------------

        elif isinstance(node, RevertStatement):

            print(
                f"{spacing}Revert"
            )

        # ----------------------------------------------------
        # Expression Statement
        # ----------------------------------------------------

        elif isinstance(node, ExpressionStatement):

            print(
                f"{spacing}ExpressionStatement"
            )

            self.print(
                node.expression,
                indent + 1
            )

        # ----------------------------------------------------
        # Literal
        # ----------------------------------------------------

        elif isinstance(node, Literal):

            print(
                f"{spacing}Literal: "
                f"{node.value} "
                f"({node.type.name})"
            )

        # ----------------------------------------------------
        # Identifier
        # ----------------------------------------------------

        elif isinstance(node, Identifier):

            print(
                f"{spacing}Identifier: "
                f"{node.name}"
            )

        # ----------------------------------------------------
        # Binary Expression
        # ----------------------------------------------------

        elif isinstance(node, BinaryExpression):

            print(
                f"{spacing}BinaryExpression: "
                f"{node.operator}"
            )

            print(
                f"{spacing}  Left:"
            )

            self.print(
                node.left,
                indent + 2
            )

            print(
                f"{spacing}  Right:"
            )

            self.print(
                node.right,
                indent + 2
            )

        # ----------------------------------------------------
        # Unary Expression
        # ----------------------------------------------------

        elif isinstance(node, UnaryExpression):

            print(
                f"{spacing}UnaryExpression: "
                f"{node.operator}"
            )

            self.print(
                node.operand,
                indent + 1
            )

        elif isinstance(node, UpdateExpression):

            position = "prefix" if node.prefix else "postfix"
            print(
                f"{spacing}UpdateExpression: "
                f"{position} {node.operator}"
            )
            self.print(node.operand, indent + 1)

        # ----------------------------------------------------
        # Function Call
        # ----------------------------------------------------

        elif isinstance(node, FunctionCall):

            print(
                f"{spacing}FunctionCall: "
                f"{node.name}"
            )

            for argument in node.arguments:

                self.print(
                    argument,
                    indent + 1
                )

        else:

            print(
                f"{spacing}{node}"
            )


# ============================================================
# SIMPLE AST TEST
# ============================================================

if __name__ == "__main__":

    program = Program(

        contract=Contract(

            name="Bank",

            states=[
                StateDeclaration(
                    name="balance",
                    type=Type("int")
                ),

                StateDeclaration(
                    name="owner",
                    type=Type("address")
                )
            ],

            functions=[
                FunctionDeclaration(

                    name="deposit",

                    parameters=[
                        Parameter(
                            name="amount",
                            type=Type("int")
                        )
                    ],

                    body=Block(
                        statements=[
                            RequireStatement(
                                condition=BinaryExpression(
                                    left=Identifier("amount"),
                                    operator=">",
                                    right=Literal(
                                        value=0,
                                        type=Type("int")
                                    )
                                )
                            ),

                            Assignment(
                                name="balance",
                                value=BinaryExpression(
                                    left=Identifier("balance"),
                                    operator="+",
                                    right=Identifier("amount")
                                )
                            )
                        ]
                    )
                )
            ]
        )
    )

    printer = ASTPrinter()

    printer.print(program)
