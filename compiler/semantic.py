from lexer import Lexer
from parser import Parser, ParserError

from ast_nodes import (
    Program,
    Contract,
    Type,
    StateDeclaration,
    Parameter,
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


# ============================================================
# SEMANTIC ERROR
# ============================================================

class SemanticError(Exception):
    pass


# ============================================================
# SEMANTIC ANALYZER
# ============================================================

class SemanticAnalyzer:

    def __init__(self, program):

        self.program = program

        # Contract-level symbols
        self.global_symbols = {}

        # Function information
        self.functions = {}

        # Current function
        self.current_function = None

        # Local symbols
        self.local_symbols = {}

        # Collected errors
        self.errors = []

    # ========================================================
    # ERROR HANDLING
    # ========================================================

    def error(self, message):

        self.errors.append(message)

    # ========================================================
    # MAIN ANALYSIS
    # ========================================================

    def analyze(self):

        self.visit_program()

        if self.errors:

            print()
            print("Semantic analysis failed.")
            print()

            for error in self.errors:
                print(f"ERROR: {error}")

            return False

        print()
        print("Semantic analysis successful.")
        print()

        return True

    # ========================================================
    # PROGRAM
    # ========================================================

    def visit_program(self):

        self.visit_contract(
            self.program.contract
        )

    # ========================================================
    # CONTRACT
    # ========================================================

    def visit_contract(self, contract):

        # ----------------------------------------------------
        # Register state variables
        # ----------------------------------------------------

        for state in contract.states:

            if state.name in self.global_symbols:

                self.error(
                    f"Duplicate state variable "
                    f"'{state.name}'."
                )

            else:

                self.global_symbols[state.name] = state.type

        # ----------------------------------------------------
        # Register functions
        # ----------------------------------------------------

        for function in contract.functions:

            if function.name in self.functions:

                self.error(
                    f"Duplicate function "
                    f"'{function.name}'."
                )

            else:

                self.functions[function.name] = function

        # ----------------------------------------------------
        # Analyze functions
        # ----------------------------------------------------

        for function in contract.functions:

            self.visit_function(function)

    # ========================================================
    # FUNCTION
    # ========================================================

    def visit_function(self, function):

        self.current_function = function

        # New local scope
        self.local_symbols = {}

        # ----------------------------------------------------
        # Register parameters
        # ----------------------------------------------------

        for parameter in function.parameters:

            if parameter.name in self.local_symbols:

                self.error(
                    f"Duplicate parameter "
                    f"'{parameter.name}' "
                    f"in function '{function.name}'."
                )

            else:

                self.local_symbols[
                    parameter.name
                ] = parameter.type

        # ----------------------------------------------------
        # Analyze function body
        # ----------------------------------------------------

        self.visit_block(function.body)

        self.current_function = None

        self.local_symbols = {}

    # ========================================================
    # BLOCK
    # ========================================================

    def visit_block(self, block):

        for statement in block.statements:

            self.visit_statement(statement)

    # ========================================================
    # STATEMENTS
    # ========================================================

    def visit_statement(self, statement):

        # ----------------------------------------------------
        # Variable declaration
        # ----------------------------------------------------

        if isinstance(
            statement,
            VariableDeclaration
        ):

            self.visit_variable_declaration(
                statement
            )

        # ----------------------------------------------------
        # Assignment
        # ----------------------------------------------------

        elif isinstance(
            statement,
            Assignment
        ):

            self.visit_assignment(
                statement
            )

        # ----------------------------------------------------
        # If
        # ----------------------------------------------------

        elif isinstance(
            statement,
            IfStatement
        ):

            self.visit_if_statement(
                statement
            )

        # ----------------------------------------------------
        # While
        # ----------------------------------------------------

        elif isinstance(
            statement,
            WhileStatement
        ):

            self.visit_while_statement(
                statement
            )

        # ----------------------------------------------------
        # Return
        # ----------------------------------------------------

        elif isinstance(
            statement,
            ReturnStatement
        ):

            self.visit_return_statement(
                statement
            )

        # ----------------------------------------------------
        # Require
        # ----------------------------------------------------

        elif isinstance(
            statement,
            RequireStatement
        ):

            self.visit_require_statement(
                statement
            )

        # ----------------------------------------------------
        # Revert
        # ----------------------------------------------------

        elif isinstance(
            statement,
            RevertStatement
        ):

            return

        # ----------------------------------------------------
        # Expression statement
        # ----------------------------------------------------

        elif isinstance(
            statement,
            ExpressionStatement
        ):

            self.get_expression_type(
                statement.expression
            )

    # ========================================================
    # VARIABLE DECLARATION
    # ========================================================

    def visit_variable_declaration(
        self,
        declaration
    ):

        name = declaration.name

        # Check duplicate local variable
        if name in self.local_symbols:

            self.error(
                f"Variable '{name}' is already "
                f"declared in function "
                f"'{self.current_function.name}'."
            )

            return

        # Check conflict with state variable
        if name in self.global_symbols:

            self.error(
                f"Local variable '{name}' conflicts "
                f"with state variable '{name}'."
            )

            return

        # Register variable
        self.local_symbols[name] = declaration.type

        # Check initializer
        if declaration.initializer is not None:

            expression_type = (
                self.get_expression_type(
                    declaration.initializer
                )
            )

            if not self.types_compatible(
                declaration.type,
                expression_type
            ):

                self.error(
                    f"Cannot initialize variable "
                    f"'{name}' of type "
                    f"'{declaration.type.name}' "
                    f"with type "
                    f"'{expression_type.name}'."
                )

    # ========================================================
    # ASSIGNMENT
    # ========================================================

    def visit_assignment(self, assignment):

        variable_type = self.lookup_variable(
            assignment.name
        )

        if variable_type is None:

            self.error(
                f"Undefined variable "
                f"'{assignment.name}'."
            )

            # Still analyze expression
            self.get_expression_type(
                assignment.value
            )

            return

        value_type = self.get_expression_type(
            assignment.value
        )

        if not self.types_compatible(
            variable_type,
            value_type
        ):

            self.error(
                f"Cannot assign type "
                f"'{value_type.name}' "
                f"to variable "
                f"'{assignment.name}' "
                f"of type "
                f"'{variable_type.name}'."
            )

    # ========================================================
    # IF
    # ========================================================

    def visit_if_statement(self, statement):

        condition_type = self.get_expression_type(
            statement.condition
        )

        if condition_type.name != "bool":

            self.error(
                "If condition must be of type 'bool'."
            )

        self.visit_block(
            statement.then_branch
        )

        if statement.else_branch is not None:

            self.visit_block(
                statement.else_branch
            )

    # ========================================================
    # WHILE
    # ========================================================

    def visit_while_statement(self, statement):

        condition_type = self.get_expression_type(
            statement.condition
        )

        if condition_type.name != "bool":

            self.error(
                "While condition must be of type 'bool'."
            )

        self.visit_block(
            statement.body
        )

    # ========================================================
    # RETURN
    # ========================================================

    def visit_return_statement(self, statement):

        expected_type = (
            self.current_function.return_type
        )

        # Function declared without return type
        if expected_type is None:

            if statement.value is not None:

                self.error(
                    f"Function "
                    f"'{self.current_function.name}' "
                    f"does not return a value."
                )

            return

        # Function expects a value
        if statement.value is None:

            self.error(
                f"Function "
                f"'{self.current_function.name}' "
                f"must return type "
                f"'{expected_type.name}'."
            )

            return

        actual_type = self.get_expression_type(
            statement.value
        )

        if not self.types_compatible(
            expected_type,
            actual_type
        ):

            self.error(
                f"Function "
                f"'{self.current_function.name}' "
                f"expects return type "
                f"'{expected_type.name}', "
                f"but got "
                f"'{actual_type.name}'."
            )

    # ========================================================
    # REQUIRE
    # ========================================================

    def visit_require_statement(self, statement):

        condition_type = self.get_expression_type(
            statement.condition
        )

        if condition_type.name != "bool":

            self.error(
                "Require condition must be "
                "of type 'bool'."
            )

    # ========================================================
    # EXPRESSION TYPE
    # ========================================================

    def get_expression_type(self, expression):

        # ----------------------------------------------------
        # Literal
        # ----------------------------------------------------

        if isinstance(expression, Literal):

            return expression.type

        # ----------------------------------------------------
        # Identifier
        # ----------------------------------------------------

        if isinstance(expression, Identifier):

            variable_type = self.lookup_variable(
                expression.name
            )

            if variable_type is None:

                self.error(
                    f"Undefined variable "
                    f"'{expression.name}'."
                )

                return Type("unknown")

            return variable_type

        # ----------------------------------------------------
        # Binary expression
        # ----------------------------------------------------

        if isinstance(
            expression,
            BinaryExpression
        ):

            return self.get_binary_expression_type(
                expression
            )

        # ----------------------------------------------------
        # Unary expression
        # ----------------------------------------------------

        if isinstance(
            expression,
            UnaryExpression
        ):

            return self.get_unary_expression_type(
                expression
            )

        if isinstance(expression, UpdateExpression):
            return self.get_update_expression_type(expression)

        # ----------------------------------------------------
        # Function call
        # ----------------------------------------------------

        if isinstance(
            expression,
            FunctionCall
        ):

            return self.get_function_call_type(
                expression
            )

        # ----------------------------------------------------
        # Unknown
        # ----------------------------------------------------

        return Type("unknown")

    # ========================================================
    # BINARY EXPRESSION
    # ========================================================

    def get_binary_expression_type(
        self,
        expression
    ):

        left_type = self.get_expression_type(
            expression.left
        )

        right_type = self.get_expression_type(
            expression.right
        )

        operator = expression.operator

        # ----------------------------------------------------
        # Arithmetic
        # ----------------------------------------------------

        if operator in (
            "+",
            "-",
            "*",
            "/",
            "%"
        ):

            if left_type.name not in (
                "int",
                "float"
            ):

                self.error(
                    f"Operator '{operator}' "
                    f"cannot be applied to "
                    f"type '{left_type.name}'."
                )

                return Type("unknown")

            if right_type.name not in (
                "int",
                "float"
            ):

                self.error(
                    f"Operator '{operator}' "
                    f"cannot be applied to "
                    f"type '{right_type.name}'."
                )

                return Type("unknown")

            # Float result if either side is float
            if (
                left_type.name == "float"
                or right_type.name == "float"
            ):

                return Type("float")

            return Type("int")

        # ----------------------------------------------------
        # Comparison
        # ----------------------------------------------------

        if operator in (
            "<",
            ">",
            "<=",
            ">="
        ):

            if left_type.name not in (
                "int",
                "float"
            ):

                self.error(
                    f"Cannot compare "
                    f"type '{left_type.name}'."
                )

            if right_type.name not in (
                "int",
                "float"
            ):

                self.error(
                    f"Cannot compare "
                    f"type '{right_type.name}'."
                )

            return Type("bool")

        # ----------------------------------------------------
        # Equality
        # ----------------------------------------------------

        if operator in (
            "==",
            "!="
        ):

            if not self.types_compatible(
                left_type,
                right_type
            ):

                self.error(
                    f"Cannot compare "
                    f"'{left_type.name}' "
                    f"with "
                    f"'{right_type.name}'."
                )

            return Type("bool")

        # ----------------------------------------------------
        # Logical
        # ----------------------------------------------------

        if operator in (
            "&&",
            "||"
        ):

            if left_type.name != "bool":

                self.error(
                    f"Left operand of "
                    f"'{operator}' must be bool."
                )

            if right_type.name != "bool":

                self.error(
                    f"Right operand of "
                    f"'{operator}' must be bool."
                )

            return Type("bool")

        # ----------------------------------------------------
        # Bitwise AND and shift operators
        # ----------------------------------------------------

        if operator in ("&", "<<", ">>"):

            if left_type.name != "int":

                self.error(
                    f"Left operand of '{operator}' "
                    f"must be of type 'int'."
                )

            if right_type.name != "int":

                self.error(
                    f"Right operand of '{operator}' "
                    f"must be of type 'int'."
                )

            return Type("int")

        return Type("unknown")

    # ========================================================
    # UNARY EXPRESSION
    # ========================================================

    def get_unary_expression_type(
        self,
        expression
    ):

        operand_type = self.get_expression_type(
            expression.operand
        )

        if expression.operator == "!":

            if operand_type.name != "bool":

                self.error(
                    "Operator '!' requires "
                    "a boolean operand."
                )

            return Type("bool")

        if expression.operator == "-":

            if operand_type.name not in (
                "int",
                "float"
            ):

                self.error(
                    "Unary '-' requires "
                    "a numeric operand."
                )

            return operand_type

        return Type("unknown")

    def get_update_expression_type(self, expression):
        if not isinstance(expression.operand, Identifier):
            self.error(
                "Increment/decrement target must be a variable identifier."
            )
            self.get_expression_type(expression.operand)
            return Type("unknown")

        operand_type = self.lookup_variable(expression.operand.name)
        if operand_type is None:
            self.error(
                f"Undefined variable '{expression.operand.name}'."
            )
            return Type("unknown")

        if operand_type.name != "int":
            self.error(
                f"Operator '{expression.operator}' requires an 'int' "
                f"identifier, but '{expression.operand.name}' has type "
                f"'{operand_type.name}'."
            )
            return Type("unknown")

        return Type("int")

    # ========================================================
    # FUNCTION CALL
    # ========================================================

    def get_function_call_type(
        self,
        expression
    ):

        function = self.functions.get(
            expression.name
        )

        # ----------------------------------------------------
        # Unknown function
        # ----------------------------------------------------

        if function is None:

            self.error(
                f"Undefined function "
                f"'{expression.name}'."
            )

            # Analyze arguments anyway
            for argument in expression.arguments:

                self.get_expression_type(
                    argument
                )

            return Type("unknown")

        # ----------------------------------------------------
        # Check argument count
        # ----------------------------------------------------

        expected_count = len(
            function.parameters
        )

        actual_count = len(
            expression.arguments
        )

        if expected_count != actual_count:

            self.error(
                f"Function '{expression.name}' "
                f"expects "
                f"{expected_count} argument(s), "
                f"but got "
                f"{actual_count}."
            )

        # ----------------------------------------------------
        # Check argument types
        # ----------------------------------------------------

        count = min(
            expected_count,
            actual_count
        )

        for i in range(count):

            expected_type = (
                function.parameters[i].type
            )

            actual_type = (
                self.get_expression_type(
                    expression.arguments[i]
                )
            )

            if not self.types_compatible(
                expected_type,
                actual_type
            ):

                self.error(
                    f"Argument {i + 1} of "
                    f"function '{expression.name}' "
                    f"expects "
                    f"'{expected_type.name}', "
                    f"but got "
                    f"'{actual_type.name}'."
                )

        # Analyze extra arguments
        for i in range(
            count,
            actual_count
        ):

            self.get_expression_type(
                expression.arguments[i]
            )

        # ----------------------------------------------------
        # Return type
        # ----------------------------------------------------

        if function.return_type is None:

            return Type("void")

        return function.return_type

    # ========================================================
    # VARIABLE LOOKUP
    # ========================================================

    def lookup_variable(self, name):

        # Local variable / parameter
        if name in self.local_symbols:

            return self.local_symbols[name]

        # State variable
        if name in self.global_symbols:

            return self.global_symbols[name]

        return None

    # ========================================================
    # TYPE COMPATIBILITY
    # ========================================================

    def types_compatible(
        self,
        expected,
        actual
    ):

        if (
            expected.name == "unknown"
            or actual.name == "unknown"
        ):

            return True

        if expected.name == actual.name:

            return True

        # Allow int -> float
        if (
            expected.name == "float"
            and actual.name == "int"
        ):

            return True

        return False


# ============================================================
# TEST PROGRAM
# ============================================================

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

    # --------------------------------------------------------
    # LEXICAL ANALYSIS
    # --------------------------------------------------------

    lexer = Lexer(source)

    tokens = lexer.tokenize()

    # --------------------------------------------------------
    # SYNTAX ANALYSIS
    # --------------------------------------------------------

    parser = Parser(tokens)

    try:

        program = parser.parse()

    except ParserError as error:

        print()
        print("Parser Error:")
        print(error)
        exit()

    # --------------------------------------------------------
    # SEMANTIC ANALYSIS
    # --------------------------------------------------------

    analyzer = SemanticAnalyzer(program)

    analyzer.analyze()
