from enum import Enum, auto


class TokenType(Enum):
    # Keywords
    CONTRACT = auto()
    STATE = auto()
    FUNCTION = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    RETURN = auto()
    TRUE = auto()
    FALSE = auto()
    REQUIRE = auto()
    REVERT = auto()

    # Types
    INT = auto()
    FLOAT = auto()
    BOOL = auto()
    STRING_TYPE = auto()
    ADDRESS = auto()

    # Identifiers and literals
    IDENTIFIER = auto()
    INTEGER_LITERAL = auto()
    FLOAT_LITERAL = auto()
    STRING_LITERAL = auto()

    # Arithmetic operators
    PLUS = auto()
    MINUS = auto()
    PLUS_PLUS = auto()
    MINUS_MINUS = auto()
    MULTIPLY = auto()
    DIVIDE = auto()
    MODULO = auto()

    # Relational operators
    LESS = auto()
    GREATER = auto()
    LESS_EQUAL = auto()
    GREATER_EQUAL = auto()
    EQUAL_EQUAL = auto()
    NOT_EQUAL = auto()

    # Logical operators
    AND = auto()
    OR = auto()
    NOT = auto()

    # Bitwise / shift operators
    SHIFT_LEFT = auto()
    SHIFT_RIGHT = auto()
    BIT_AND = auto()

    # Assignment
    ASSIGN = auto()

    # Delimiters
    LEFT_PAREN = auto()
    RIGHT_PAREN = auto()
    LEFT_BRACE = auto()
    RIGHT_BRACE = auto()
    LEFT_BRACKET = auto()
    RIGHT_BRACKET = auto()

    COMMA = auto()
    SEMICOLON = auto()
    COLON = auto()
    DOT = auto()

    # End of file
    EOF = auto()


class Token:
    def __init__(self, token_type, value, line, column):
        self.type = token_type
        self.value = value
        self.line = line
        self.column = column

    def __str__(self):
        return f"{self.type.name}({self.value!r}) at {self.line}:{self.column}"

    def __repr__(self):
        return self.__str__()


class Lexer:
    KEYWORDS = {
        "contract": TokenType.CONTRACT,
        "state": TokenType.STATE,
        "function": TokenType.FUNCTION,
        "if": TokenType.IF,
        "else": TokenType.ELSE,
        "while": TokenType.WHILE,
        "return": TokenType.RETURN,
        "true": TokenType.TRUE,
        "false": TokenType.FALSE,
        "require": TokenType.REQUIRE,
        "revert": TokenType.REVERT,

        "int": TokenType.INT,
        "float": TokenType.FLOAT,
        "bool": TokenType.BOOL,
        "string": TokenType.STRING_TYPE,
        "address": TokenType.ADDRESS,
    }

    TWO_CHARACTER_OPERATORS = {
        "++": TokenType.PLUS_PLUS,
        "--": TokenType.MINUS_MINUS,
        "<<": TokenType.SHIFT_LEFT,
        ">>": TokenType.SHIFT_RIGHT,
        "<=": TokenType.LESS_EQUAL,
        ">=": TokenType.GREATER_EQUAL,
        "==": TokenType.EQUAL_EQUAL,
        "!=": TokenType.NOT_EQUAL,
        "&&": TokenType.AND,
        "||": TokenType.OR,
    }

    ONE_CHARACTER_OPERATORS = {
        "+": TokenType.PLUS,
        "-": TokenType.MINUS,
        "*": TokenType.MULTIPLY,
        "/": TokenType.DIVIDE,
        "%": TokenType.MODULO,

        "<": TokenType.LESS,
        ">": TokenType.GREATER,

        "!": TokenType.NOT,
        "&": TokenType.BIT_AND,

        "=": TokenType.ASSIGN,

        "(": TokenType.LEFT_PAREN,
        ")": TokenType.RIGHT_PAREN,
        "{": TokenType.LEFT_BRACE,
        "}": TokenType.RIGHT_BRACE,
        "[": TokenType.LEFT_BRACKET,
        "]": TokenType.RIGHT_BRACKET,

        ",": TokenType.COMMA,
        ";": TokenType.SEMICOLON,
        ":": TokenType.COLON,
        ".": TokenType.DOT,
    }

    def __init__(self, source):
        self.source = source
        self.position = 0
        self.line = 1
        self.column = 1

    def current_char(self):
        if self.position >= len(self.source):
            return "\0"

        return self.source[self.position]

    def peek_char(self, offset=1):
        index = self.position + offset

        if index >= len(self.source):
            return "\0"

        return self.source[index]

    def advance(self, count=1):
        for _ in range(count):
            if self.position >= len(self.source):
                return

            char = self.source[self.position]

            self.position += 1

            if char == "\n":
                self.line += 1
                self.column = 1
            else:
                self.column += 1

    def skip_whitespace(self):
        while True:
            char = self.current_char()

            if char in " \t\r\n":
                self.advance()
                continue

            break

    def skip_comment(self):
        # Single-line comment
        if self.current_char() == "/" and self.peek_char() == "/":
            self.advance(2)

            while self.current_char() not in ("\n", "\0"):
                self.advance()

            return True

        # Multi-line comment
        if self.current_char() == "/" and self.peek_char() == "*":
            start_line = self.line
            start_column = self.column

            self.advance(2)

            while True:
                if self.current_char() == "\0":
                    raise SyntaxError(
                        f"Unterminated comment at line "
                        f"{start_line}, column {start_column}"
                    )

                if self.current_char() == "*" and self.peek_char() == "/":
                    self.advance(2)
                    break

                self.advance()

            return True

        return False

    def read_identifier(self):
        start_position = self.position
        start_line = self.line
        start_column = self.column

        while True:
            char = self.current_char()

            if char.isalnum() or char == "_":
                self.advance()
            else:
                break

        value = self.source[start_position:self.position]

        token_type = self.KEYWORDS.get(
            value,
            TokenType.IDENTIFIER
        )

        return Token(
            token_type,
            value,
            start_line,
            start_column
        )

    def read_number(self):
        start_position = self.position
        start_line = self.line
        start_column = self.column

        has_decimal = False

        while self.current_char().isdigit():
            self.advance()

        if self.current_char() == "." and self.peek_char().isdigit():
            has_decimal = True
            self.advance()

            while self.current_char().isdigit():
                self.advance()

        value = self.source[start_position:self.position]

        if has_decimal:
            token_type = TokenType.FLOAT_LITERAL
        else:
            token_type = TokenType.INTEGER_LITERAL

        return Token(
            token_type,
            value,
            start_line,
            start_column
        )

    def read_string(self):
        start_line = self.line
        start_column = self.column

        self.advance()

        characters = []

        while True:
            char = self.current_char()

            if char == "\0":
                raise SyntaxError(
                    f"Unterminated string at line "
                    f"{start_line}, column {start_column}"
                )

            if char == '"':
                self.advance()
                break

            if char == "\\":
                self.advance()

                escaped = self.current_char()

                if escaped == "\0":
                    raise SyntaxError(
                        f"Unterminated string at line "
                        f"{start_line}, column {start_column}"
                    )

                escape_sequences = {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    '"': '"',
                    "\\": "\\",
                }

                characters.append(
                    escape_sequences.get(
                        escaped,
                        escaped
                    )
                )

                self.advance()

            else:
                characters.append(char)
                self.advance()

        value = "".join(characters)

        return Token(
            TokenType.STRING_LITERAL,
            value,
            start_line,
            start_column
        )

    def tokenize(self):
        tokens = []

        while self.position < len(self.source):

            self.skip_whitespace()

            if self.position >= len(self.source):
                break

            if self.skip_comment():
                continue

            char = self.current_char()

            start_line = self.line
            start_column = self.column

            # Identifier or keyword
            if char.isalpha() or char == "_":
                tokens.append(self.read_identifier())
                continue

            # Number
            if char.isdigit():
                tokens.append(self.read_number())
                continue

            # String
            if char == '"':
                tokens.append(self.read_string())
                continue

            # Two-character operators
            two_char = char + self.peek_char()

            if two_char in self.TWO_CHARACTER_OPERATORS:
                token_type = self.TWO_CHARACTER_OPERATORS[two_char]

                self.advance(2)

                tokens.append(
                    Token(
                        token_type,
                        two_char,
                        start_line,
                        start_column
                    )
                )

                continue

            # One-character operators / delimiters
            if char in self.ONE_CHARACTER_OPERATORS:
                token_type = self.ONE_CHARACTER_OPERATORS[char]

                self.advance()

                tokens.append(
                    Token(
                        token_type,
                        char,
                        start_line,
                        start_column
                    )
                )

                continue

            raise SyntaxError(
                f"Unexpected character '{char}' "
                f"at line {start_line}, column {start_column}"
            )

        tokens.append(
            Token(
                TokenType.EOF,
                "",
                self.line,
                self.column
            )
        )

        return tokens


if __name__ == "__main__":

    source_code = """
    contract Bank {

        state balance : int;

        function test(amount : int) {

            int a = amount * 2;
            int b = amount * 4;
            int c = 8 * amount;

            int d = amount << 1;
            int e = amount >> 2;
            int f = amount & 1;

            return;
        }
    }
    """

    lexer = Lexer(source_code)

    tokens = lexer.tokenize()

    print("=" * 60)
    print("LEXER TEST")
    print("=" * 60)

    for token in tokens:
        print(token)

    print("=" * 60)
    print("Lexing successful!")
    print("=" * 60)
