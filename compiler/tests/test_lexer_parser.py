import pytest

from ast_nodes import (
    BinaryExpression,
    ExpressionStatement,
    Identifier,
    UpdateExpression,
    VariableDeclaration,
)
from codegen import CodeGenerator
from lexer import Lexer, TokenType
from parser import Parser, ParserError


def parse_source(source):
    return Parser(Lexer(source).tokenize()).parse()


def test_lexer_tokenizes_comments_operators_and_escaped_strings():
    source = r'''
    // single-line comment
    contract Lex {
        /* multi-line
           comment */
        function f() {
            string text = "line\nquote\"";
            int value = 8 << 1;
            bool check = true && false || !false;
        }
    }
    '''

    tokens = Lexer(source).tokenize()
    token_values = [(token.type, token.value) for token in tokens]

    assert (TokenType.CONTRACT, "contract") in token_values
    assert (TokenType.SHIFT_LEFT, "<<") in token_values
    assert (TokenType.AND, "&&") in token_values
    assert (TokenType.OR, "||") in token_values
    assert (TokenType.NOT, "!") in token_values
    assert (TokenType.STRING_LITERAL, 'line\nquote"') in token_values
    assert tokens[-1].type is TokenType.EOF


def test_lexer_tokenizes_prefix_and_postfix_increment_decrement():
    tokens = Lexer("++x x++ --y y--").tokenize()

    assert [(token.type, token.value) for token in tokens] == [
        (TokenType.PLUS_PLUS, "++"),
        (TokenType.IDENTIFIER, "x"),
        (TokenType.IDENTIFIER, "x"),
        (TokenType.PLUS_PLUS, "++"),
        (TokenType.MINUS_MINUS, "--"),
        (TokenType.IDENTIFIER, "y"),
        (TokenType.IDENTIFIER, "y"),
        (TokenType.MINUS_MINUS, "--"),
        (TokenType.EOF, ""),
    ]


def test_parser_builds_distinct_prefix_and_postfix_update_nodes_and_codegen_roundtrips():
    source = """
    contract UpdateExpressions {
        state total : int;

        function adjust(value : int) : int {
            int previous = value++;
            ++total;
            int current = --value;
            total--;
            return previous + current;
        }
    }
    """
    program = parse_source(source)
    function = program.contract.functions[0]
    previous = function.body.statements[0].initializer
    prefix_statement = function.body.statements[1]
    current = function.body.statements[2].initializer
    postfix_statement = function.body.statements[3]

    assert isinstance(previous, UpdateExpression)
    assert (previous.operator, previous.prefix) == ("++", False)
    assert isinstance(previous.operand, Identifier)
    assert previous.operand.name == "value"
    assert isinstance(prefix_statement, ExpressionStatement)
    assert isinstance(prefix_statement.expression, UpdateExpression)
    assert (prefix_statement.expression.operator,
            prefix_statement.expression.prefix) == ("++", True)
    assert prefix_statement.expression.operand.name == "total"
    assert isinstance(current, UpdateExpression)
    assert (current.operator, current.prefix) == ("--", True)
    assert isinstance(postfix_statement, ExpressionStatement)
    assert isinstance(postfix_statement.expression, UpdateExpression)
    assert (postfix_statement.expression.operator,
            postfix_statement.expression.prefix) == ("--", False)

    generated = CodeGenerator().generate(program)
    assert "int previous = value++;" in generated
    assert "++total;" in generated
    assert "int current = --value;" in generated
    assert "total--;" in generated
    assert parse_source(generated) == program


@pytest.mark.parametrize(
    "expression",
    ["(value + 1)++", "++(value + 1)", "readValue()++", "1++"],
)
def test_parser_rejects_non_identifier_update_targets(expression):
    source = f"""
    contract InvalidUpdateTarget {{
        function readValue() : int {{ return 1; }}
        function run(value : int) : int {{ return {expression}; }}
    }}
    """

    with pytest.raises(ParserError):
        parse_source(source)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("@", "Unexpected character '@' at line 1, column 1"),
        ("\"unfinished", "Unterminated string at line 1, column 1"),
        ("/* unfinished", "Unterminated comment at line 1, column 1"),
    ],
)
def test_lexer_reports_invalid_input_with_source_location(source, message):
    with pytest.raises(SyntaxError, match=message.replace("'", "\\'")):
        Lexer(source).tokenize()


def test_parser_builds_contract_and_respects_expression_precedence():
    program = parse_source(
        """
        contract Parse {
            state total : int;
            function calculate() : int {
                int value = 1 + 2 * 3 << 1;
                return value;
            }
        }
        """
    )

    assert program.contract.name == "Parse"
    assert program.contract.states[0].name == "total"
    declaration = program.contract.functions[0].body.statements[0]
    assert isinstance(declaration, VariableDeclaration)
    expression = declaration.initializer
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "<<"
    assert expression.left.operator == "+"
    assert expression.left.right.operator == "*"


def test_parser_accepts_supported_statements_and_function_calls():
    program = parse_source(
        """
        contract Statements {
            state count : int;
            function increment(value : int) : int {
                int local = value;
                if (local > 0) {
                    count = count + local;
                } else {
                    revert();
                }
                while (false) {
                    count = count - 1;
                }
                require(count >= 0);
                return local;
            }
            function run() {
                increment(1);
            }
        }
        """
    )

    assert len(program.contract.functions) == 2


@pytest.mark.parametrize(
    "source",
    [
        "contract Broken { function f() { int value = 1 } }",
        "contract Broken { function f() {",
        "contract Broken { int value; }",
    ],
)
def test_parser_rejects_malformed_syntax(source):
    with pytest.raises(ParserError):
        parse_source(source)
