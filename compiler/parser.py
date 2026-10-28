from lexer import Lexer, TokenType

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
    ASTPrinter,
)


class ParserError(Exception):
    pass


class Parser:

    def __init__(self, tokens):
        self.tokens = tokens
        self.position = 0

    def current(self):
        return self.tokens[self.position]

    def peek(self, offset=1):
        index = self.position + offset

        if index >= len(self.tokens):
            return self.tokens[-1]

        return self.tokens[index]

    def advance(self):
        token = self.current()

        if self.position < len(self.tokens) - 1:
            self.position += 1

        return token

    def check(self, *token_types):
        return self.current().type in token_types

    def match(self, *token_types):
        if self.check(*token_types):
            return self.advance()

        return None

    def expect(self, token_type, message=None):
        if self.check(token_type):
            return self.advance()

        token = self.current()

        if message is None:
            message = (
                f"Expected {token_type.name}, "
                f"but found '{token.value}'"
            )

        raise ParserError(
            f"{message} "
            f"at line {token.line}, column {token.column}"
        )

    # ========================================================
    # PROGRAM
    # ========================================================

    def parse(self):
        contract = self.parse_contract()

        self.expect(
            TokenType.EOF,
            "Expected end of file"
        )

        return Program(contract=contract)

    # ========================================================
    # CONTRACT
    # ========================================================

    def parse_contract(self):
        self.expect(
            TokenType.CONTRACT,
            "Expected 'contract'"
        )

        name = self.expect(
            TokenType.IDENTIFIER,
            "Expected contract name"
        )

        self.expect(
            TokenType.LEFT_BRACE,
            "Expected '{' after contract name"
        )

        states = []
        functions = []

        while not self.check(TokenType.RIGHT_BRACE):

            if self.check(TokenType.EOF):
                token = self.current()
                raise ParserError(
                    f"Unexpected end of file at line "
                    f"{token.line}, column {token.column}"
                )

            if self.check(TokenType.STATE):
                states.append(
                    self.parse_state_declaration()
                )

            elif self.check(TokenType.FUNCTION):
                functions.append(
                    self.parse_function_declaration()
                )

            else:
                token = self.current()

                raise ParserError(
                    f"Expected state or function declaration, "
                    f"but found '{token.value}' "
                    f"at line {token.line}, "
                    f"column {token.column}"
                )

        self.expect(
            TokenType.RIGHT_BRACE,
            "Expected '}' after contract"
        )

        return Contract(
            name=name.value,
            states=states,
            functions=functions
        )

    # ========================================================
    # STATE DECLARATION
    # ========================================================

    def parse_state_declaration(self):
        self.expect(
            TokenType.STATE,
            "Expected 'state'"
        )

        name = self.expect(
            TokenType.IDENTIFIER,
            "Expected state variable name"
        )

        self.expect(
            TokenType.COLON,
            "Expected ':' after state variable name"
        )

        variable_type = self.parse_type()

        self.expect(
            TokenType.SEMICOLON,
            "Expected ';' after state declaration"
        )

        return StateDeclaration(
            name=name.value,
            type=variable_type
        )

    # ========================================================
    # TYPE
    # ========================================================

    def parse_type(self):
        token = self.current()

        valid_types = (
            TokenType.INT,
            TokenType.FLOAT,
            TokenType.BOOL,
            TokenType.STRING_TYPE,
            TokenType.ADDRESS
        )

        if token.type not in valid_types:
            raise ParserError(
                f"Expected data type, "
                f"but found '{token.value}' "
                f"at line {token.line}, "
                f"column {token.column}"
            )

        self.advance()

        return Type(token.value)

    # ========================================================
    # FUNCTION DECLARATION
    # ========================================================

    def parse_function_declaration(self):
        self.expect(
            TokenType.FUNCTION,
            "Expected 'function'"
        )

        name = self.expect(
            TokenType.IDENTIFIER,
            "Expected function name"
        )

        self.expect(
            TokenType.LEFT_PAREN,
            "Expected '(' after function name"
        )

        parameters = self.parse_parameters()

        self.expect(
            TokenType.RIGHT_PAREN,
            "Expected ')' after parameters"
        )

        return_type = None

        if self.match(TokenType.COLON):
            return_type = self.parse_type()

        body = self.parse_block()

        return FunctionDeclaration(
            name=name.value,
            parameters=parameters,
            return_type=return_type,
            body=body
        )

    # ========================================================
    # PARAMETERS
    # ========================================================

    def parse_parameters(self):
        parameters = []

        if self.check(TokenType.RIGHT_PAREN):
            return parameters

        while True:
            name = self.expect(
                TokenType.IDENTIFIER,
                "Expected parameter name"
            )

            self.expect(
                TokenType.COLON,
                "Expected ':' after parameter name"
            )

            parameter_type = self.parse_type()

            parameters.append(
                Parameter(
                    name=name.value,
                    type=parameter_type
                )
            )

            if not self.match(TokenType.COMMA):
                break

        return parameters

    # ========================================================
    # BLOCK
    # ========================================================

    def parse_block(self):
        self.expect(
            TokenType.LEFT_BRACE,
            "Expected '{'"
        )

        statements = []

        while not self.check(TokenType.RIGHT_BRACE):

            if self.check(TokenType.EOF):
                token = self.current()

                raise ParserError(
                    "Unexpected end of file. Expected '}' "
                    f"at line {token.line}, "
                    f"column {token.column}"
                )

            statements.append(
                self.parse_statement()
            )

        self.expect(
            TokenType.RIGHT_BRACE,
            "Expected '}'"
        )

        return Block(statements=statements)

    # ========================================================
    # STATEMENTS
    # ========================================================

    def parse_statement(self):

        if self.check(
            TokenType.INT,
            TokenType.FLOAT,
            TokenType.BOOL,
            TokenType.STRING_TYPE,
            TokenType.ADDRESS
        ):
            return self.parse_variable_declaration()

        if self.check(TokenType.IF):
            return self.parse_if_statement()

        if self.check(TokenType.WHILE):
            return self.parse_while_statement()

        if self.check(TokenType.RETURN):
            return self.parse_return_statement()

        if self.check(TokenType.REQUIRE):
            return self.parse_require_statement()

        if self.check(TokenType.REVERT):
            return self.parse_revert_statement()

        if self.check(TokenType.IDENTIFIER):

            if self.peek().type == TokenType.ASSIGN:
                return self.parse_assignment()

            if self.peek().type in (
                TokenType.LEFT_PAREN,
                TokenType.PLUS_PLUS,
                TokenType.MINUS_MINUS,
            ):
                expression = self.parse_expression()

                self.expect(
                    TokenType.SEMICOLON,
                    "Expected ';' after expression"
                )

                return ExpressionStatement(
                    expression=expression
                )

        if self.check(TokenType.PLUS_PLUS, TokenType.MINUS_MINUS):
            expression = self.parse_expression()

            self.expect(
                TokenType.SEMICOLON,
                "Expected ';' after expression"
            )

            return ExpressionStatement(expression=expression)

        token = self.current()

        raise ParserError(
            f"Unexpected token '{token.value}' "
            f"at line {token.line}, "
            f"column {token.column}"
        )

    # ========================================================
    # VARIABLE DECLARATION
    # ========================================================

    def parse_variable_declaration(self):
        variable_type = self.parse_type()

        name = self.expect(
            TokenType.IDENTIFIER,
            "Expected variable name"
        )

        initializer = None

        if self.match(TokenType.ASSIGN):
            initializer = self.parse_expression()

        self.expect(
            TokenType.SEMICOLON,
            "Expected ';' after variable declaration"
        )

        return VariableDeclaration(
            name=name.value,
            type=variable_type,
            initializer=initializer
        )

    # ========================================================
    # ASSIGNMENT
    # ========================================================

    def parse_assignment(self):
        name = self.expect(
            TokenType.IDENTIFIER,
            "Expected variable name"
        )

        self.expect(
            TokenType.ASSIGN,
            "Expected '=' in assignment"
        )

        value = self.parse_expression()

        self.expect(
            TokenType.SEMICOLON,
            "Expected ';' after assignment"
        )

        return Assignment(
            name=name.value,
            value=value
        )

    # ========================================================
    # IF
    # ========================================================

    def parse_if_statement(self):
        self.expect(
            TokenType.IF,
            "Expected 'if'"
        )

        self.expect(
            TokenType.LEFT_PAREN,
            "Expected '(' after 'if'"
        )

        condition = self.parse_expression()

        self.expect(
            TokenType.RIGHT_PAREN,
            "Expected ')' after condition"
        )

        then_branch = self.parse_block()
        else_branch = None

        if self.match(TokenType.ELSE):
            else_branch = self.parse_block()

        return IfStatement(
            condition=condition,
            then_branch=then_branch,
            else_branch=else_branch
        )

    # ========================================================
    # WHILE
    # ========================================================

    def parse_while_statement(self):
        self.expect(
            TokenType.WHILE,
            "Expected 'while'"
        )

        self.expect(
            TokenType.LEFT_PAREN,
            "Expected '(' after 'while'"
        )

        condition = self.parse_expression()

        self.expect(
            TokenType.RIGHT_PAREN,
            "Expected ')' after condition"
        )

        body = self.parse_block()

        return WhileStatement(
            condition=condition,
            body=body
        )

    # ========================================================
    # RETURN
    # ========================================================

    def parse_return_statement(self):
        self.expect(
            TokenType.RETURN,
            "Expected 'return'"
        )

        value = None

        if not self.check(TokenType.SEMICOLON):
            value = self.parse_expression()

        self.expect(
            TokenType.SEMICOLON,
            "Expected ';' after return"
        )

        return ReturnStatement(value=value)

    # ========================================================
    # REQUIRE
    # ========================================================

    def parse_require_statement(self):
        self.expect(
            TokenType.REQUIRE,
            "Expected 'require'"
        )

        self.expect(
            TokenType.LEFT_PAREN,
            "Expected '(' after 'require'"
        )

        condition = self.parse_expression()

        self.expect(
            TokenType.RIGHT_PAREN,
            "Expected ')' after require condition"
        )

        self.expect(
            TokenType.SEMICOLON,
            "Expected ';' after require"
        )

        return RequireStatement(condition=condition)

    # ========================================================
    # REVERT
    # ========================================================

    def parse_revert_statement(self):
        self.expect(
            TokenType.REVERT,
            "Expected 'revert'"
        )

        self.expect(
            TokenType.LEFT_PAREN,
            "Expected '(' after 'revert'"
        )

        self.expect(
            TokenType.RIGHT_PAREN,
            "Expected ')' after 'revert'"
        )

        self.expect(
            TokenType.SEMICOLON,
            "Expected ';' after 'revert'"
        )

        return RevertStatement()

    # ========================================================
    # EXPRESSIONS
    # Precedence: ||, &&, &, equality, comparison,
    # shifts, +/-, */%, unary, primary
    # ========================================================

    def parse_expression(self):
        return self.parse_logical_or()

    def parse_logical_or(self):
        expression = self.parse_logical_and()

        while self.match(TokenType.OR):
            right = self.parse_logical_and()

            expression = BinaryExpression(
                left=expression,
                operator="||",
                right=right
            )

        return expression

    def parse_logical_and(self):
        expression = self.parse_bitwise_and()

        while self.match(TokenType.AND):
            right = self.parse_bitwise_and()

            expression = BinaryExpression(
                left=expression,
                operator="&&",
                right=right
            )

        return expression

    def parse_bitwise_and(self):
        expression = self.parse_equality()

        while self.match(TokenType.BIT_AND):
            right = self.parse_equality()

            expression = BinaryExpression(
                left=expression,
                operator="&",
                right=right
            )

        return expression

    def parse_equality(self):
        expression = self.parse_comparison()

        while True:
            if self.match(TokenType.EQUAL_EQUAL):
                operator = "=="

            elif self.match(TokenType.NOT_EQUAL):
                operator = "!="

            else:
                break

            right = self.parse_comparison()

            expression = BinaryExpression(
                left=expression,
                operator=operator,
                right=right
            )

        return expression

    def parse_comparison(self):
        expression = self.parse_shift()

        while True:
            if self.match(TokenType.LESS):
                operator = "<"

            elif self.match(TokenType.LESS_EQUAL):
                operator = "<="

            elif self.match(TokenType.GREATER):
                operator = ">"

            elif self.match(TokenType.GREATER_EQUAL):
                operator = ">="

            else:
                break

            right = self.parse_shift()

            expression = BinaryExpression(
                left=expression,
                operator=operator,
                right=right
            )

        return expression

    def parse_shift(self):
        expression = self.parse_term()

        while True:
            if self.match(TokenType.SHIFT_LEFT):
                operator = "<<"

            elif self.match(TokenType.SHIFT_RIGHT):
                operator = ">>"

            else:
                break

            right = self.parse_term()

            expression = BinaryExpression(
                left=expression,
                operator=operator,
                right=right
            )

        return expression

    def parse_term(self):
        expression = self.parse_factor()

        while True:
            if self.match(TokenType.PLUS):
                operator = "+"

            elif self.match(TokenType.MINUS):
                operator = "-"

            else:
                break

            right = self.parse_factor()

            expression = BinaryExpression(
                left=expression,
                operator=operator,
                right=right
            )

        return expression

    def parse_factor(self):
        expression = self.parse_unary()

        while True:
            if self.match(TokenType.MULTIPLY):
                operator = "*"

            elif self.match(TokenType.DIVIDE):
                operator = "/"

            elif self.match(TokenType.MODULO):
                operator = "%"

            else:
                break

            right = self.parse_unary()

            expression = BinaryExpression(
                left=expression,
                operator=operator,
                right=right
            )

        return expression

    # ========================================================
    # UNARY
    # ========================================================

    def parse_unary(self):
        if self.match(TokenType.PLUS_PLUS):
            operand = self.parse_unary()
            if not isinstance(operand, Identifier):
                raise ParserError(
                    "Prefix '++' requires a variable identifier."
                )
            return UpdateExpression(
                operator="++", operand=operand, prefix=True
            )

        if self.match(TokenType.MINUS_MINUS):
            operand = self.parse_unary()
            if not isinstance(operand, Identifier):
                raise ParserError(
                    "Prefix '--' requires a variable identifier."
                )
            return UpdateExpression(
                operator="--", operand=operand, prefix=True
            )

        if self.match(TokenType.NOT):
            operand = self.parse_unary()

            return UnaryExpression(
                operator="!",
                operand=operand
            )

        if self.match(TokenType.MINUS):
            operand = self.parse_unary()

            return UnaryExpression(
                operator="-",
                operand=operand
            )

        return self.parse_postfix()

    def parse_postfix(self):
        expression = self.parse_primary()

        if self.match(TokenType.PLUS_PLUS):
            if not isinstance(expression, Identifier):
                raise ParserError(
                    "Postfix '++' requires a variable identifier."
                )
            return UpdateExpression(
                operator="++", operand=expression, prefix=False
            )

        if self.match(TokenType.MINUS_MINUS):
            if not isinstance(expression, Identifier):
                raise ParserError(
                    "Postfix '--' requires a variable identifier."
                )
            return UpdateExpression(
                operator="--", operand=expression, prefix=False
            )

        return expression

    # ========================================================
    # PRIMARY
    # ========================================================

    def parse_primary(self):
        token = self.current()

        if self.match(TokenType.INTEGER_LITERAL):
            return Literal(
                value=int(token.value),
                type=Type("int")
            )

        if self.match(TokenType.FLOAT_LITERAL):
            return Literal(
                value=float(token.value),
                type=Type("float")
            )

        if self.match(TokenType.STRING_LITERAL):
            return Literal(
                value=token.value,
                type=Type("string")
            )

        if self.match(TokenType.TRUE):
            return Literal(
                value=True,
                type=Type("bool")
            )

        if self.match(TokenType.FALSE):
            return Literal(
                value=False,
                type=Type("bool")
            )

        if self.match(TokenType.IDENTIFIER):
            name = token.value

            if self.match(TokenType.LEFT_PAREN):
                arguments = []

                if not self.check(TokenType.RIGHT_PAREN):
                    while True:
                        arguments.append(
                            self.parse_expression()
                        )

                        if not self.match(TokenType.COMMA):
                            break

                self.expect(
                    TokenType.RIGHT_PAREN,
                    "Expected ')' after function arguments"
                )

                return FunctionCall(
                    name=name,
                    arguments=arguments
                )

            return Identifier(name=name)

        if self.match(TokenType.LEFT_PAREN):
            expression = self.parse_expression()

            self.expect(
                TokenType.RIGHT_PAREN,
                "Expected ')'"
            )

            return expression

        raise ParserError(
            f"Unexpected token '{token.value}' "
            f"at line {token.line}, "
            f"column {token.column}"
        )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    source = """
    contract Bank {
        state balance : int;
        state owner : address;

        function test(amount : int) {
            int a = amount * 2;
            int b = amount * 4;
            int c = 8 * amount;

            int d = amount << 1;
            int e = amount >> 2;
            int f = amount & 1;

            require(amount > 0);
            balance = balance + amount;
        }

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

    lexer = Lexer(source)
    tokens = lexer.tokenize()
    parser = Parser(tokens)

    try:
        program = parser.parse()

        print()
        print("Parsing successful!")
        print()

        printer = ASTPrinter()
        printer.print(program)

    except ParserError as error:
        print()
        print("Parser Error:")
        print(error)
