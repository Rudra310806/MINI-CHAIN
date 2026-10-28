import contextlib
import io

import pytest

from ast_nodes import (
    BinaryExpression,
    ExpressionStatement,
    FunctionCall,
    Identifier,
    Literal,
    UpdateExpression,
    UnaryExpression,
)
from codegen import CodeGenerator
from domain_analyzer import DomainAnalyzer
from lexer import Lexer
from optimizer import Optimizer
from parser import Parser, ParserError
from semantic import SemanticAnalyzer

from test_optimizer_pipeline import SOURCE as EXISTING_OPTIMIZER_SOURCE


def parse_source(source):
    return Parser(Lexer(source).tokenize()).parse()


def validate_generated_source(source):
    generated_program = parse_source(source)
    analyzer = SemanticAnalyzer(generated_program)
    with contextlib.redirect_stdout(io.StringIO()):
        valid = analyzer.analyze()
    assert valid, analyzer.errors
    return generated_program


def test_existing_optimizer_example_has_exact_rewrites_and_valid_output():
    program = parse_source(EXISTING_OPTIMIZER_SOURCE)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)
    rule_ids = {item.rule_id for item in optimizer.optimizations}

    assert "int doubled = (amount << 1);" in optimized_source
    assert "int simplified = amount;" in optimized_source
    assert "int constant = 12;" in optimized_source
    assert "balance = (balance + doubled);" in optimized_source
    assert "999" not in optimized_source
    assert {"OPT-007", "OPT-008", "OPT-003", "OPT-016"} <= rule_ids

    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("factor", "factor_on_left", "shift_count", "rule_id"),
    [
        (2, False, 1, "OPT-016"),
        (2, True, 1, "OPT-017"),
        (4, False, 2, "OPT-018"),
        (4, True, 2, "OPT-019"),
        (8, False, 3, "OPT-020"),
        (8, True, 3, "OPT-021"),
        (16, False, 4, "OPT-025"),
        (16, True, 4, "OPT-025"),
        (32, False, 5, "OPT-025"),
    ],
)
def test_integer_power_of_two_multiplication_reduces_to_shift(
    factor, factor_on_left, shift_count, rule_id
):
    expression = f"{factor} * x" if factor_on_left else f"x * {factor}"
    source = f"""
    contract Strength {{
        function calculate(x : int) : int {{
            int result = {expression};
            return result;
        }}
    }}
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert f"int result = (x << {shift_count});" in optimized_source
    initializer = program.contract.functions[0].body.statements[0].initializer
    assert isinstance(initializer, BinaryExpression)
    assert isinstance(initializer.left, Identifier)
    assert initializer.left.name == "x"
    assert initializer.operator == "<<"
    assert isinstance(initializer.right, Literal)
    assert initializer.right.type.name == "int"
    assert initializer.right.value == shift_count
    assert [item.rule_id for item in optimizer.optimizations] == [rule_id]
    source_pattern = (
        f"Strength reduction: {factor} * x -> x << {shift_count}."
        if factor_on_left
        else f"Strength reduction: x * {factor} -> x << {shift_count}."
    )
    assert optimizer.optimizations[0].message == source_pattern
    validate_generated_source(optimized_source)


@pytest.mark.parametrize("expression", ["(-8) * 2", "x * -2"])
def test_negative_integer_multipliers_are_not_strength_reduced(expression):
    program = parse_source(
        f"""
        contract NegativeMultiplier {{
            function calculate(x : int) : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, BinaryExpression)
    assert result.operator == "*"
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


def test_non_power_of_two_multiplication_remains_unchanged():
    program = parse_source(
        """
        contract NonPowerOfTwo {
            function calculate(x : int) : int {
                return x * 3;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[0].body.statements[0].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "*"
    assert "return (x * 3);" in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


def test_power_of_two_above_shift_guard_remains_unchanged():
    factor = str(1 << 4097)
    program = parse_source(
        f"""
        contract LargeStrengthFactor {{
            function calculate(x : int) : int {{
                return x * {factor};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[0].body.statements[0].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "*"
    assert f"return (x * {factor});" in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("parameter_type", "return_type", "expression"),
    [
        ("float", "float", "x * 2"),
        ("float", "float", "2 * x"),
        ("int", "float", "x * 2.0"),
        ("int", "float", "2.0 * x"),
    ],
)
def test_float_and_mixed_multiplication_are_not_strength_reduced(
    parameter_type, return_type, expression
):
    program = parse_source(
        f"""
        contract FloatStrengthReduction {{
            function calculate(x : {parameter_type}) : {return_type} {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, BinaryExpression)
    assert result.operator == "*"
    assert optimizer.optimizations == []
    assert f"return ({expression});" in optimized_source
    validate_generated_source(optimized_source)


def test_nested_and_effectful_operands_are_reduced_once_without_reordering_calls():
    source = """
    contract StrengthReductionEffects {
        state call_count : int;

        function mutate() : int {
            call_count = call_count + 1;
            return 3;
        }

        function nested(x : int) : int {
            return (x * 2) * 4;
        }

        function callRight() : int {
            return mutate() * 2;
        }

        function callLeft() : int {
            return 2 * mutate();
        }

        function callNested() : int {
            return (mutate() + 1) * 4;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    functions = program.contract.functions
    nested = functions[1].body.statements[0].value
    call_right = functions[2].body.statements[0].value
    call_left = functions[3].body.statements[0].value
    call_nested = functions[4].body.statements[0].value

    assert isinstance(nested, BinaryExpression)
    assert nested.operator == "<<" and nested.right.value == 2
    assert isinstance(nested.left, BinaryExpression)
    assert nested.left.operator == "<<" and nested.left.right.value == 1
    assert isinstance(call_right, BinaryExpression)
    assert call_right.operator == "<<"
    assert isinstance(call_right.left, FunctionCall)
    assert call_right.left.name == "mutate"
    assert isinstance(call_left, BinaryExpression)
    assert call_left.operator == "<<"
    assert isinstance(call_left.left, FunctionCall)
    assert call_left.left.name == "mutate"
    assert isinstance(call_nested, BinaryExpression)
    assert call_nested.operator == "<<" and call_nested.right.value == 2
    assert isinstance(call_nested.left, BinaryExpression)
    assert isinstance(call_nested.left.left, FunctionCall)
    assert call_nested.left.left.name == "mutate"

    assert "return ((x << 1) << 2);" in optimized_source
    assert "return (mutate() << 1);" in optimized_source
    assert "return ((mutate() + 1) << 2);" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == [
        "OPT-027", "OPT-016", "OPT-018", "OPT-016", "OPT-017", "OPT-018",
    ]
    assert sum(
        isinstance(node, FunctionCall)
        for node in (call_right.left, call_left.left, call_nested.left.left)
    ) == 3
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 3", 5),
        ("8 - 3", 5),
        ("4 * 5", 20),
        ("2 - 5", -3),
        ("9007199254740993 + 1", 9007199254740994),
        ("100000000000000000000 * 3", 300000000000000000000),
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
    ],
)
def test_exact_integer_add_subtract_and_multiply_fold(expression, expected):
    source = f"""
    contract IntegerConstantFold {{
        function calculate() : int {{
            return {expression};
        }}
    }}
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    return_expression = program.contract.functions[0].body.statements[0].value
    assert isinstance(return_expression, Literal)
    assert return_expression.type.name == "int"
    assert return_expression.value == expected
    assert f"return {expected};" in optimized_source
    assert sum(
        item.rule_id == "OPT-007" for item in optimizer.optimizations
    ) == expression.count("+") + expression.count("-") + expression.count("*")
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("expression", "return_type", "operator"),
    [
        ("7 & 3", "int", "&"),
        ("1 < 2", "bool", "<"),
        ("1.5 + 2.5", "float", "+"),
        ("9007199254740993 / 1.0", "float", "/"),
    ],
)
def test_numeric_operations_outside_integer_division_and_modulo_remain_unfolded(
    expression, return_type, operator
):
    source = f"""
    contract NumericFoldDeferred {{
        function calculate() : {return_type} {{
            return {expression};
        }}
    }}
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    return_expression = program.contract.functions[0].body.statements[0].value
    assert isinstance(return_expression, BinaryExpression)
    assert return_expression.operator == operator
    assert "OPT-007" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1 << 2", 4),
        ("3 << 2", 12),
        ("8 >> 1", 4),
        ("9 >> 2", 2),
        ("16 >> 4", 1),
        ("0 << 5", 0),
        ("5 << 0", 5),
        ("5 >> 0", 5),
        ("9007199254740993 << 3", 72057594037927944),
        ("3 << 100", 3802951800684688204490109616128),
    ],
)
def test_integer_literal_shifts_fold_exactly(expression, expected):
    program = parse_source(
        f"""
        contract IntegerShiftFold {{
            function calculate() : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, Literal)
    assert result.type.name == "int"
    assert result.value == expected
    assert f"return {expected};" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-007"]
    assert optimizer.optimizations[0].message == (
        f"Constant folding: {expression.split()[0]} "
        f"{expression.split()[1]} {expression.split()[2]} -> {expected}."
    )
    validate_generated_source(optimized_source)


@pytest.mark.parametrize("expression", ["1 << -1", "1 >> -1", "1 << 4097"])
def test_negative_or_oversized_shift_counts_remain_unfolded(expression):
    program = parse_source(
        f"""
        contract DeferredShiftCount {{
            function calculate() : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, BinaryExpression)
    assert result.operator in ("<<", ">>")
    assert "OPT-007" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


def test_unary_negative_shift_operand_remains_unfolded():
    program = parse_source(
        """
        contract UnaryNegativeShift {
            function calculate() : int {
                return -8 >> 1;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, BinaryExpression)
    assert isinstance(result.left, UnaryExpression)
    assert result.operator == ">>"
    assert optimizer.optimizations == []
    assert "return ((-8) >> 1);" in optimized_source
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("expression", "parameter_list"),
    [
        ("x << 2", "x : int"),
        ("8 >> x", "x : int"),
    ],
)
def test_variable_shift_expressions_remain_unchanged(expression, parameter_list):
    program = parse_source(
        f"""
        contract VariableShift {{
            function calculate({parameter_list}) : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, BinaryExpression)
    assert result.operator in ("<<", ">>")
    assert optimizer.optimizations == []
    assert f"return ({expression});" in optimized_source
    validate_generated_source(optimized_source)


def test_function_call_shift_expression_remains_unchanged():
    source = """
    contract FunctionCallShift {
        function getValue() : int {
            return 3;
        }

        function calculate() : int {
            return getValue() << 2;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[1].body.statements[0].value
    assert isinstance(result, BinaryExpression)
    assert isinstance(result.left, FunctionCall)
    assert result.operator == "<<"
    assert optimizer.optimizations == []
    assert "return (getValue() << 2);" in optimized_source
    validate_generated_source(optimized_source)


@pytest.mark.parametrize("expression", ["1.0 << 2", "1 << 2.0"])
def test_float_or_mixed_shift_expressions_remain_unfolded(expression):
    program = parse_source(
        f"""
        contract InvalidShiftTypes {{
            function calculate() : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, BinaryExpression)
    assert result.operator in ("<<", ">>")
    assert "OPT-007" not in {item.rule_id for item in optimizer.optimizations}

    analyzer = SemanticAnalyzer(program)
    with contextlib.redirect_stdout(io.StringIO()):
        valid = analyzer.analyze()
    assert not valid


@pytest.mark.parametrize(
    ("expression", "expected", "expected_message"),
    [
        ("20 / 5", 4, "Constant folding: 20 / 5 -> 4."),
        ("7 / 2", 3, "Constant folding: 7 / 2 -> 3."),
        ("8 / 3", 2, "Constant folding: 8 / 3 -> 2."),
        ("17 % 5", 2, "Constant folding: 17 % 5 -> 2."),
        ("7 % 3", 1, "Constant folding: 7 % 3 -> 1."),
        (
            "9007199254740993 / 3",
            3002399751580331,
            "Constant folding: 9007199254740993 / 3 -> 3002399751580331.",
        ),
    ],
)
def test_integer_division_and_modulo_fold_with_exact_integer_semantics(
    expression, expected, expected_message
):
    program = parse_source(
        f"""
        contract IntegerDivisionModulo {{
            function calculate() : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, Literal)
    assert result.type.name == "int"
    assert result.value == expected
    assert f"return {expected};" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-007"]
    assert optimizer.optimizations[0].message == expected_message
    validate_generated_source(optimized_source)


def test_integer_constant_fold_has_transformation_record_and_no_format_only_record():
    program = parse_source(
        """
        contract FoldReport {
            state balance : int;
            function calculate() {
                balance = (2 + 3);
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "balance = 5;" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-007"]
    assert str(optimizer.optimizations[0]) == (
        "[OPT-007] Constant folding: 2 + 3 -> 5."
    )
    validate_generated_source(optimized_source)


def test_parentheses_without_ast_transformation_do_not_create_optimization_records():
    program = parse_source(
        """
        contract ParenthesesOnly {
            state balance : int;
            function calculate(left : int, right : int) {
                balance = (left + right);
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "balance = (left + right);" in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("expression", "return_type"),
    [("-5", "int"), ("-1.5", "float")],
)
def test_numeric_unary_negation_remains_unfolded(expression, return_type):
    program = parse_source(
        f"""
        contract NumericNegationDeferred {{
            function calculate() : {return_type} {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()

    return_expression = program.contract.functions[0].body.statements[0].value
    assert isinstance(return_expression, UnaryExpression)
    assert return_expression.operator == "-"
    assert "OPT-022" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(CodeGenerator().generate(program))


@pytest.mark.parametrize(
    ("expression", "expected_value"),
    [
        ("true && false", False),
        ("true || false", True),
        ("true == false", False),
        ("true != false", True),
    ],
)
def test_boolean_constant_expressions_still_fold(expression, expected_value):
    program = parse_source(
        f"""
        contract BooleanFold {{
            function calculate() : bool {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, Literal)
    assert result.type.name == "bool"
    assert result.value is expected_value
    assert "OPT-007" in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(CodeGenerator().generate(program))


@pytest.mark.parametrize(
    ("expression", "expected_initializer", "rule_id"),
    [
        ("0 + x", "x", "OPT-009"),
        ("x - 0", "x", "OPT-010"),
        ("x * 1", "x", "OPT-011"),
        ("1 * x", "x", "OPT-012"),
        ("x * 0", "0", "OPT-013"),
        ("0 * x", "0", "OPT-014"),
        ("x / 1", "x", "OPT-015"),
    ],
)
def test_algebraic_simplifications_have_exact_generated_initializers(
    expression, expected_initializer, rule_id
):
    source = f"""
    contract Algebra {{
        function calculate(x : int) : int {{
            int result = {expression};
            return result;
        }}
    }}
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert f"int result = {expected_initializer};" in optimized_source
    assert rule_id in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("expression", "expected_return"),
    [
        ("(0.0 + x) / 2", "return ((0.0 + x) / 2);"),
        ("x / 1.0", "return (x / 1.0);"),
        ("x * 0.0", "return (x * 0.0);"),
    ],
)
def test_float_algebraic_identities_are_not_simplified_to_integer_expressions(
    expression, expected_return
):
    source = f"""
    contract FloatIdentity {{
        function calculate(x : int) : float {{
            return {expression};
        }}
    }}
    """
    validate_generated_source(source)

    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert expected_return in optimized_source
    return_expression = program.contract.functions[0].body.statements[0].value
    assert optimizer.infer_type(return_expression) == "float"
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("source_literal", "expected_literal"),
    [
        ("100000000000000000000.0", "100000000000000000000.0"),
        ("0.0000001", "0.0000001"),
    ],
    ids=["large-exponent", "small-exponent"],
)
def test_codegen_emits_exponent_free_float_literals_that_round_trip(
    source_literal, expected_literal
):
    source = f"""
    contract FloatFormatting {{
        function value() : float {{
            return {source_literal};
        }}
    }}
    """
    program = parse_source(source)
    original_value = (
        program.contract.functions[0].body.statements[0].value.value
    )

    generated_source = CodeGenerator().generate(program)

    assert f"return {expected_literal};" in generated_source
    reparsed = validate_generated_source(generated_source)
    generated_value = (
        reparsed.contract.functions[0].body.statements[0].value.value
    )
    assert type(generated_value) is float
    assert generated_value == original_value


def test_float_returning_function_call_is_not_misclassified_as_integer():
    source = """
    contract FloatCallIdentity {
        function getValue() : float {
            return 0.0;
        }

        function calculate() : float {
            return getValue() + 0;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "return (getValue() + 0);" in optimized_source
    return_expression = program.contract.functions[1].body.statements[0].value
    assert optimizer.infer_type(return_expression) == "float"
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("expression", "expected_initializer", "call_side"),
    [
        ("0 * (mutate() + 1)", "(0 * (mutate() + 1))", "right"),
        ("(mutate() + 1) * 0", "((mutate() + 1) * 0)", "left"),
    ],
)
def test_zero_multiplication_preserves_function_call_evaluation(
    expression, expected_initializer, call_side
):
    source = f"""
    contract EffectfulZeroProduct {{
        state total : int;

        function mutate() : int {{
            total = total + 1;
            return 2;
        }}

        function calculate() : int {{
            int result = {expression};
            return result;
        }}
    }}
    """
    validate_generated_source(source)

    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    initializer = program.contract.functions[1].body.statements[0].initializer
    assert isinstance(initializer, BinaryExpression)
    assert initializer.operator == "*"

    call_expression = (
        initializer.right if call_side == "right" else initializer.left
    )
    assert isinstance(call_expression, BinaryExpression)
    assert isinstance(call_expression.left, FunctionCall)
    assert call_expression.left.name == "mutate"

    assert f"int result = {expected_initializer};" in optimized_source
    rule_ids = {item.rule_id for item in optimizer.optimizations}
    assert "OPT-013" not in rule_ids
    assert "OPT-014" not in rule_ids
    validate_generated_source(optimized_source)


def test_optimizer_preserves_numeric_expressions_and_removes_dead_code():
    source = """
    contract ControlFlow {
        state total : int;
        function calculate(x : int) : int {
            int folded = 3 * 4;
            int simplified = x + 0;
            if (true) {
                total = total + 1;
            } else {
                total = 0;
            }
            while (false) {
                total = 2;
            }
            return -5;
            total = 999;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()

    optimized_ast_return = program.contract.functions[0].body.statements[-1]
    assert isinstance(optimized_ast_return.value, UnaryExpression)
    assert optimized_ast_return.value.operator == "-"

    optimized_source = CodeGenerator().generate(program)
    rule_ids = {item.rule_id for item in optimizer.optimizations}

    assert "int folded = 12;" in optimized_source
    assert "int simplified = x;" in optimized_source
    assert "total++;" in optimized_source
    assert "while (" not in optimized_source
    assert "total = 0;" not in optimized_source
    assert "total = 999;" not in optimized_source
    assert "return (-5);" in optimized_source
    assert {"OPT-007", "OPT-008", "OPT-003", "OPT-005", "OPT-006"} <= rule_ids
    assert "OPT-022" not in rule_ids

    optimized_program = validate_generated_source(optimized_source)
    optimized_function = optimized_program.contract.functions[0]
    return_statement = optimized_function.body.statements[-1]
    assert isinstance(return_statement.value, UnaryExpression)
    assert return_statement.value.operator == "-"
    assert isinstance(return_statement.value.operand, Literal)
    assert return_statement.value.operand.value == 5


def test_optimizer_folds_boolean_negation_and_selects_false_branch():
    program = parse_source(
        """
        contract BooleanBranch {
            function choose() : int {
                if (!true) {
                    return 1;
                } else {
                    return 2;
                }
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)
    rule_ids = {item.rule_id for item in optimizer.optimizations}

    assert "if (" not in optimized_source
    assert "return 1;" not in optimized_source
    assert "return 2;" in optimized_source
    assert {"OPT-023", "OPT-004"} <= rule_ids
    validate_generated_source(optimized_source)


def test_discarded_if_false_branch_does_not_report_inner_optimizations():
    program = parse_source(
        """
        contract DiscardedIfBranch {
            function run() {
                if (false) {
                    int dead = 1 + 2;
                }
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "dead" not in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == [
        "OPT-004",
    ]


def test_discarded_false_loop_body_does_not_report_inner_optimizations():
    program = parse_source(
        """
        contract DiscardedFalseLoop {
            function run() {
                while (false) {
                    int dead = 1 + 2;
                }
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "dead" not in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == [
        "OPT-005",
    ]


def test_false_loop_with_effectful_condition_is_preserved():
    source = """
    contract EffectfulLoopCondition {
        state calls : int;

        function shouldContinue() : bool {
            calls = calls + 1;
            return false;
        }

        function run() {
            while (shouldContinue()) {
                calls = 99;
            }
            calls = 1;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "while (shouldContinue())" in optimized_source
    assert "calls = 99;" in optimized_source
    assert "calls = 1;" in optimized_source
    assert "OPT-005" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


def test_nested_false_loop_removal_preserves_following_outer_loop_statements():
    source = """
    contract NestedLoopRemoval {
        state value : int;

        function run(outer_flag : bool) {
            while (outer_flag) {
                while (false) {
                    value = 1;
                }
                value = 2;
            }
            value = 3;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "while (outer_flag)" in optimized_source
    assert "while (false)" not in optimized_source
    assert "value = 1;" not in optimized_source
    assert "value = 2;" in optimized_source
    assert "value = 3;" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-005"]
    validate_generated_source(optimized_source)


def test_terminating_conditional_inside_loop_does_not_remove_outer_tail():
    source = """
    contract LoopReturnBoundary {
        state value : int;

        function run(loop_flag : bool, branch_flag : bool) {
            while (loop_flag) {
                if (branch_flag) {
                    return;
                } else {
                    return;
                }
                value = 1;
            }
            value = 2;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "while (loop_flag)" in optimized_source
    assert "if (branch_flag)" in optimized_source
    assert "value = 1;" not in optimized_source
    assert "value = 2;" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-006"]
    validate_generated_source(optimized_source)


def test_constant_true_loop_and_following_code_are_not_removed():
    source = """
    contract ConstantTrueLoop {
        state value : int;

        function run() {
            while (true) {
                value = 1;
            }
            value = 2;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "while (true)" in optimized_source
    assert "value = 1;" in optimized_source
    assert "value = 2;" in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


def test_condition_folding_and_control_flow_removal_records_are_preserved():
    if_program = parse_source(
        """
        contract FoldedIfCondition {
            function choose() : int {
                if (!true) {
                    int dead = 1 + 2;
                    return 1;
                } else {
                    return 2;
                }
            }
        }
        """
    )
    if_optimizer = Optimizer(if_program)
    if_optimizer.optimize()
    if_source = CodeGenerator().generate(if_program)
    if_rule_ids = [item.rule_id for item in if_optimizer.optimizations]

    assert "return 2;" in if_source
    assert "return 1;" not in if_source
    assert "dead" not in if_source
    assert "OPT-023" in if_rule_ids
    assert "OPT-004" in if_rule_ids
    assert not any(
        item.rule_id in {"OPT-001", "OPT-007"}
        and ("dead" in item.message or "1 + 2" in item.message)
        for item in if_optimizer.optimizations
    )

    while_program = parse_source(
        """
        contract FoldedWhileCondition {
            function run() {
                while (!true) {
                    int dead = 1 + 2;
                }
            }
        }
        """
    )
    while_optimizer = Optimizer(while_program)
    while_optimizer.optimize()
    while_source = CodeGenerator().generate(while_program)
    while_rule_ids = [item.rule_id for item in while_optimizer.optimizations]

    assert "while (" not in while_source
    assert "dead" not in while_source
    assert "OPT-023" in while_rule_ids
    assert "OPT-005" in while_rule_ids
    assert not any(
        item.rule_id in {"OPT-001", "OPT-007"}
        and ("dead" in item.message or "1 + 2" in item.message)
        for item in while_optimizer.optimizations
    )


def test_repeated_constant_folds_are_reported_once_per_occurrence():
    program = parse_source(
        """
        contract RepeatedFolds {
            function run() {
                bool first = true && false;
                bool second = true && false;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "bool first = false;" in optimized_source
    assert "bool second = false;" in optimized_source
    fold_records = [
        item for item in optimizer.optimizations
        if item.rule_id == "OPT-007"
    ]
    assert len(fold_records) == 2
    assert [str(item) for item in fold_records] == [
        "[OPT-007] Constant folding: True && False -> False.",
        "[OPT-007] Constant folding: True && False -> False.",
    ]
    assert [item.rule_id for item in optimizer.optimizations] == [
        "OPT-007", "OPT-007",
    ]


def test_division_by_zero_constant_expression_is_not_folded():
    program = parse_source(
        """
        contract DivideByZero {
            function calculate() : int {
                int value = 1 / 0;
                return value;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "int value = (1 / 0);" in optimized_source
    assert "OPT-007" not in {item.rule_id for item in optimizer.optimizations}
    assert isinstance(
        program.contract.functions[0].body.statements[0].initializer,
        BinaryExpression,
    )
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("guard", "divisor", "shift_count"),
    [
        ("value >= 0", 2, 1),
        ("value > 0", 4, 2),
        ("0 <= value", 8, 3),
        ("0 < value", 16, 4),
    ],
)
def test_guarded_nonnegative_integer_division_reduces_to_arithmetic_shift(
    guard, divisor, shift_count
):
    program = parse_source(
        f"""
        contract GuardedDivision {{
            function calculate(value : int) : int {{
                require({guard});
                return value / {divisor};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[0].body.statements[-1].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == ">>"
    assert isinstance(expression.left, Identifier)
    assert expression.left.name == "value"
    assert isinstance(expression.right, Literal)
    assert expression.right.type.name == "int"
    assert expression.right.value == shift_count
    assert f"return (value >> {shift_count});" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-026"]
    assert optimizer.optimizations[0].message == (
        f"Strength reduction: value / {divisor} -> value >> "
        f"{shift_count} after a nonnegative require guard."
    )
    validate_generated_source(optimized_source)


def test_unguarded_potentially_negative_division_is_not_strength_reduced():
    program = parse_source(
        """
        contract PossiblyNegativeDivision {
            function calculate(value : int) : int {
                return value / 2;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[0].body.statements[0].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "/"
    assert "return (value / 2);" in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


def test_direct_nonnegative_guard_proves_local_identifier_range():
    program = parse_source(
        """
        contract GuardedLocalDivision {
            function calculate(input : int) : int {
                int local_value = input;
                require(local_value >= 0);
                return local_value / 4;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[0].body.statements[-1].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == ">>"
    assert "return (local_value >> 2);" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-026"]
    validate_generated_source(optimized_source)


def test_nonnegative_guard_is_invalidated_by_assignment():
    program = parse_source(
        """
        contract InvalidatedDivisionGuard {
            function calculate(value : int) : int {
                require(value >= 0);
                value = -1;
                return value / 2;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[0].body.statements[-1].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "/"
    assert "return (value / 2);" in optimized_source
    assert "OPT-026" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


def test_guard_in_only_one_branch_does_not_prove_nonnegative_after_join():
    program = parse_source(
        """
        contract ConditionalDivisionGuard {
            function calculate(value : int, flag : bool) : int {
                if (flag) {
                    require(value >= 0);
                }
                return value / 2;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[0].body.statements[-1].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "/"
    assert "return (value / 2);" in optimized_source
    assert "OPT-026" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("parameter_type", "return_type", "expression"),
    [
        ("float", "float", "value / 2"),
        ("int", "float", "value / 2.0"),
    ],
)
def test_float_and_mixed_type_division_are_not_strength_reduced(
    parameter_type, return_type, expression
):
    source = f"""
    contract TypedDivision {{
        function calculate(value : {parameter_type}) : {return_type} {{
            require(value >= 0);
            return {expression};
        }}
    }}
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[-1].value
    assert isinstance(result, BinaryExpression)
    assert result.operator == "/"
    assert "OPT-026" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


@pytest.mark.parametrize("divisor", [0, "-2", 3, "divisor", 1 << 4097])
def test_unsupported_divisors_are_not_strength_reduced(divisor):
    divisor_source = str(divisor)
    parameter = ", divisor : int" if divisor == "divisor" else ""
    expression = "value / divisor" if divisor == "divisor" else f"value / {divisor_source}"
    program = parse_source(
        f"""
        contract UnsupportedDivisionDivisor {{
            function calculate(value : int{parameter}) : int {{
                require(value >= 0);
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[-1].value
    assert isinstance(result, BinaryExpression)
    assert result.operator == "/"
    assert "OPT-026" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


def test_state_variable_nonnegativity_is_not_assumed_from_require():
    program = parse_source(
        """
        contract StateDivisionGuard {
            state value : int;
            function calculate() : int {
                require(value >= 0);
                return value / 2;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[0].body.statements[-1].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "/"
    assert "return (value / 2);" in optimized_source
    assert "OPT-026" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


def test_literal_division_is_still_constant_folded_before_strength_reduction():
    program = parse_source(
        """
        contract LiteralDivisionOrder {
            function calculate() : int {
                return 8 / 2;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, Literal)
    assert result.value == 4
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-007"]
    assert "return 4;" in optimized_source
    validate_generated_source(optimized_source)


def test_function_call_numerator_is_not_rewritten_or_re_evaluated():
    source = """
    contract EffectfulDivisionNumerator {
        state counter : int;

        function mutate() : int {
            counter = counter + 1;
            return counter;
        }

        function calculate(value : int) : int {
            require(value >= 0);
            return mutate() / 2;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    expression = program.contract.functions[1].body.statements[1].value
    assert isinstance(expression, BinaryExpression)
    assert expression.operator == "/"
    assert isinstance(expression.left, FunctionCall)
    assert expression.left.name == "mutate"
    assert "return (mutate() / 2);" in optimized_source
    assert "OPT-026" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("expression", "operator"),
    [("x / y", "/"), ("x % 5", "%"), ("5 % x", "%")],
)
def test_variable_division_and_modulo_expressions_remain_unchanged(
    expression, operator
):
    program = parse_source(
        f"""
        contract VariableDivisionModulo {{
            function calculate(x : int, y : int) : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    result = program.contract.functions[0].body.statements[0].value
    assert isinstance(result, BinaryExpression)
    assert result.operator == operator
    assert optimizer.optimizations == []
    assert f"return ({expression});" in optimized_source
    validate_generated_source(optimized_source)


def test_large_integer_division_by_one_folds_without_losing_precision():
    program = parse_source(
        """
        contract LargeIntegerDivision {
            function calculate() : int {
                return 9007199254740993 / 1;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()

    return_value = program.contract.functions[0].body.statements[0].value
    assert isinstance(return_value, Literal)
    assert return_value.value == 9007199254740993

    rule_ids = {item.rule_id for item in optimizer.optimizations}
    assert rule_ids == {"OPT-007"}

    optimized_source = CodeGenerator().generate(program)
    assert "return 9007199254740993;" in optimized_source
    validate_generated_source(optimized_source)


def test_remainder_by_zero_constant_expression_is_not_folded():
    program = parse_source(
        """
        contract RemainderByZero {
            function calculate() : int {
                int value = 1 % 0;
                return value;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "int value = (1 % 0);" in optimized_source
    assert "OPT-007" not in {item.rule_id for item in optimizer.optimizations}
    assert isinstance(
        program.contract.functions[0].body.statements[0].initializer,
        BinaryExpression,
    )
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    "expression",
    ["-7 / 3", "7 / -3", "-7 / -3"],
)
def test_negative_integer_division_remains_unfolded_for_unary_operands(
    expression,
):
    # The grammar represents a negative source operand as UnaryExpression;
    # unary numeric folding remains outside this task.
    # This observes the optimizer's conservative policy, not runtime semantics.
    program = parse_source(
        f"""
        contract NegativeIntegerDivision {{
            function calculate() : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()

    return_value = program.contract.functions[0].body.statements[0].value
    assert isinstance(return_value, BinaryExpression)
    assert return_value.operator == "/"
    assert "OPT-007" not in {item.rule_id for item in optimizer.optimizations}


@pytest.mark.parametrize(
    "expression",
    [
        "-7 % 3",
        "7 % -3",
        "-7 % -3",
    ],
)
def test_negative_remainder_remains_unfolded_for_unary_operands(expression):
    # The grammar represents a negative source operand as UnaryExpression;
    # unary numeric folding remains outside this task.
    program = parse_source(
        f"""
        contract NegativeRemainder {{
            function calculate() : int {{
                return {expression};
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()

    return_value = program.contract.functions[0].body.statements[0].value
    assert isinstance(return_value, BinaryExpression)
    assert return_value.operator == "%"
    assert "OPT-007" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(CodeGenerator().generate(program))


def test_constant_propagation_replaces_only_known_local_values():
    program = parse_source(
        """
        contract LocalConstantPropagation {
            function calculate() : int {
                int x = 5;
                int y = x + 2;
                int z;
                x = 8;
                z = x + 1;
                return y + x + z;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "int y = 7;" in optimized_source
    assert "z = 9;" in optimized_source
    assert "x = 8;" in optimized_source
    assert "return 24;" in optimized_source
    assert "OPT-007" in {item.rule_id for item in optimizer.optimizations}
    assert sum(
        item.rule_id == "OPT-024" for item in optimizer.optimizations
    ) == 5
    assert sum(
        item.rule_id == "OPT-007" for item in optimizer.optimizations
    ) == 4
    assert not any(
        item.rule_id in {"OPT-001", "OPT-002"}
        for item in optimizer.optimizations
    )
    validate_generated_source(optimized_source)


def test_constant_propagation_invalidates_values_across_branches_and_loops():
    sources = [
        """
        contract BranchInvalidation {
            function calculate(flag : bool) : int {
                int value = 5;
                if (flag) {
                    value = 6;
                }
                return value;
            }
        }
        """,
        """
        contract LoopInvalidation {
            function calculate(flag : bool) : int {
                int value = 5;
                while (flag) {
                    value = 6;
                }
                return value;
            }
        }
        """,
    ]

    for source in sources:
        program = parse_source(source)
        optimizer = Optimizer(program)
        optimizer.optimize()
        optimized_source = CodeGenerator().generate(program)

        assert "return value;" in optimized_source
        assert "return 5;" not in optimized_source
        validate_generated_source(optimized_source)


def test_constant_propagation_merges_identical_values_from_both_branches():
    program = parse_source(
        """
        contract BranchMerge {
            function calculate(flag : bool) : int {
                int value = 5;
                if (flag) {
                    value = 7;
                } else {
                    value = 7;
                }
                return value;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "return 7;" in optimized_source
    validate_generated_source(optimized_source)


def test_nested_branch_optimization_propagates_without_reordering_state_writes():
    program = parse_source(
        """
        contract NestedBranchPropagation {
            state total : int;
            function update(flag : bool) {
                int known = 4;
                if (flag) {
                    if (true) {
                        total = known;
                    } else {
                        total = 99;
                    }
                }
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "if (flag) {" in optimized_source
    assert "total = 4;" in optimized_source
    assert "total = 99;" not in optimized_source
    assert "OPT-024" in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


def test_semantic_analyzer_rejects_shadowed_locals_before_optimization():
    program = parse_source(
        """
        contract NoBlockShadowing {
            function update() {
                int value = 1;
                if (true) {
                    int value = 2;
                }
            }
        }
        """
    )
    analyzer = SemanticAnalyzer(program)
    with contextlib.redirect_stdout(io.StringIO()):
        valid = analyzer.analyze()

    assert not valid
    assert any("already declared" in error for error in analyzer.errors)


def test_parser_still_rejects_compound_assignment_syntax():
    source = f"""
    contract UnsupportedIncrement {{
        function update() {{
            int value = 1;
            value += 1;
        }}
    }}
    """

    with pytest.raises(ParserError):
        parse_source(source)


def test_optimizer_preserves_update_expressions_and_invalidates_known_values():
    source = """
    contract UpdateOptimizerSafety {
        function calculate(value : int) : int {
            int known = 4;
            value++;
            ++known;
            return value++ + known;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "value++;" in optimized_source
    assert "++known;" in optimized_source
    assert "return (value++ + known);" in optimized_source
    assert isinstance(
        program.contract.functions[0].body.statements[1].expression,
        UpdateExpression,
    )
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("assignment", "operator", "expected_source", "report_expression"),
    [
        ("x = x + 1;", "++", "x++;", "x + 1"),
        ("x = 1 + x;", "++", "x++;", "1 + x"),
        ("x = x - 1;", "--", "x--;", "x - 1"),
    ],
)
def test_integer_increment_assignments_rewrite_to_postfix_updates(
    assignment, operator, expected_source, report_expression
):
    source = f"""
    contract IncrementAssignment {{
        function adjust(x : int) : int {{
            {assignment}
            return x;
        }}
    }}
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    statement = program.contract.functions[0].body.statements[0]
    assert isinstance(statement, ExpressionStatement)
    assert isinstance(statement.expression, UpdateExpression)
    assert statement.expression.operator == operator
    assert statement.expression.prefix is False
    assert statement.expression.operand.name == "x"
    assert expected_source in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-027"]
    assert optimizer.optimizations[0].message == (
        f"Assignment simplification: x = {report_expression} -> "
        f"x{operator}."
    )
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("function_parameters", "assignment", "expected"),
    [
        ("x : int, y : int", "x = y + 1;", "x = (y + 1);"),
        ("x : int", "x = x - 2;", "x = (x - 2);"),
        ("x : float", "x = x + 1.0;", "x = (x + 1.0);"),
        ("x : int, X : int", "x = X + 1;", "x = (X + 1);"),
    ],
)
def test_increment_assignment_rewrite_rejects_unsupported_shapes(
    function_parameters, assignment, expected
):
    source = f"""
    contract UnsupportedIncrementAssignment {{
        function adjust({function_parameters}) {{
            {assignment}
        }}
    }}
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert expected in optimized_source
    assert not any(
        item.rule_id == "OPT-027" for item in optimizer.optimizations
    )
    validate_generated_source(optimized_source)


def test_increment_assignment_rewrite_does_not_simplify_function_call_rhs():
    source = """
    contract EffectfulIncrementAssignment {
        state total : int;

        function mutate() : int {
            total = total + 2;
            return 1;
        }

        function adjust(x : int) {
            x = x + mutate();
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "x = (x + mutate());" in optimized_source
    assert optimized_source.count("x + mutate()") == 1
    assert "x++;" not in optimized_source
    assert "OPT-027" not in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


def test_increment_assignment_rewrite_is_idempotent():
    program = parse_source(
        """
        contract IncrementAssignmentIdempotence {
            function adjust(x : int) {
                x = x + 1;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    first_output = CodeGenerator().generate(program)
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-027"]

    optimizer.optimize()
    second_output = CodeGenerator().generate(program)

    assert second_output == first_output
    assert optimizer.optimizations == []
    validate_generated_source(second_output)


def test_optimizer_does_not_propagate_old_value_across_increment():
    program = parse_source(
        """
        contract UpdateInvalidatesConstant {
            function calculate() : int {
                int value = 4;
                value++;
                return value;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "int value = 4;" in optimized_source
    assert "value++;" in optimized_source
    assert "return value;" in optimized_source
    assert "return 4;" not in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


def test_optimizer_preserves_exactly_one_update_inside_function_call_argument():
    program = parse_source(
        """
        contract UpdateCallArgument {
            function consume(value : int) : int { return value; }

            function calculate(value : int) : int {
                return consume(value++);
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert optimized_source.count("value++") == 1
    assert "return consume(value++);" in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    "expression",
    ["0 * value++", "value++ * 0"],
)
def test_optimizer_does_not_discard_update_side_effect_in_zero_product(expression):
    program = parse_source(
        f"""
        contract UpdateZeroProduct {{
            function calculate(value : int) : int {{
                int result = {expression};
                return result;
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert f"int result = ({expression});" in optimized_source
    assert "value++" in optimized_source
    assert not {
        "OPT-013", "OPT-014",
    }.intersection(item.rule_id for item in optimizer.optimizations)
    validate_generated_source(optimized_source)


def test_optimizer_preserves_update_of_arbitrary_precision_integer_local():
    huge = "999999999999999999999999999999999999999999999999999999"
    program = parse_source(
        f"""
        contract UnboundedUpdate {{
            function calculate() : int {{
                int value = {huge};
                ++value;
                return value;
            }}
        }}
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert f"int value = {huge};" in optimized_source
    assert "++value;" in optimized_source
    assert "return value;" in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


def test_optimizer_is_idempotent_after_propagation_and_control_flow_rewrites():
    program = parse_source(
        """
        contract IdempotentOptimizer {
            state total : int;
            function choose() : int {
                bool enabled = true;
                int value = 9;
                if (enabled) {
                    total = value;
                    return total;
                } else {
                    return 0;
                }
                total = 100;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    first_output = CodeGenerator().generate(program)

    optimizer.optimize()
    second_output = CodeGenerator().generate(program)

    assert second_output == first_output
    assert "total = 100;" not in second_output
    validate_generated_source(second_output)


def test_both_returning_if_branches_remove_following_unreachable_statements():
    program = parse_source(
        """
        contract BothBranchesReturn {
            function choose(flag : bool) : int {
                if (flag) {
                    return 1;
                } else {
                    revert();
                }
                return 2;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "return 2;" not in optimized_source
    assert "OPT-006" in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


def test_constant_branch_removal_is_not_double_counted_as_dead_code():
    program = parse_source(
        """
        contract ConstantBranchAccounting {
            function choose() : int {
                if (false) {
                    return 1;
                } else {
                    return 2;
                }
                return 3;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "return 2;" in optimized_source
    assert "return 1;" not in optimized_source
    assert "return 3;" not in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == [
        "OPT-004", "OPT-006",
    ]
    validate_generated_source(optimized_source)


def test_dce_removes_multiple_statements_after_return_once():
    source = """
    contract MultipleUnreachableStatements {
        state before_return : int;
        state after_return : int;

        function run() {
            before_return = 1;
            return;
            after_return = 2;
            after_return = 3;
        }
    }
    """
    validate_generated_source(source)
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "before_return = 1;" in optimized_source
    assert "return;" in optimized_source
    assert "after_return = 2;" not in optimized_source
    assert "after_return = 3;" not in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-006"]
    validate_generated_source(optimized_source)


def test_dce_recurses_into_nested_branch_and_keeps_reachable_outer_code():
    source = """
    contract NestedDce {
        state inner_value : int;
        state branch_value : int;
        state outer_value : int;

        function run(outer_flag : bool, inner_flag : bool) {
            if (outer_flag) {
                if (inner_flag) {
                    inner_value = 1;
                    return;
                    inner_value = 2;
                    inner_value = 3;
                } else {
                    inner_value = 4;
                }
                branch_value = 5;
            }
            outer_value = 6;
        }
    }
    """
    validate_generated_source(source)
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "inner_value = 1;" in optimized_source
    assert "return;" in optimized_source
    assert "inner_value = 2;" not in optimized_source
    assert "inner_value = 3;" not in optimized_source
    assert "inner_value = 4;" in optimized_source
    assert "branch_value = 5;" in optimized_source
    assert "outer_value = 6;" in optimized_source
    assert [item.rule_id for item in optimizer.optimizations] == ["OPT-006"]
    validate_generated_source(optimized_source)


def test_dce_keeps_code_after_conditional_with_a_nonterminating_branch():
    source = """
    contract PartialTermination {
        state branch_value : int;
        state after_if : int;

        function run(flag : bool) {
            if (flag) {
                return;
            } else {
                branch_value = 1;
            }
            after_if = 2;
        }
    }
    """
    validate_generated_source(source)
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "return;" in optimized_source
    assert "branch_value = 1;" in optimized_source
    assert "after_if = 2;" in optimized_source
    assert not any(item.rule_id == "OPT-006" for item in optimizer.optimizations)
    validate_generated_source(optimized_source)


def test_dce_emits_no_record_when_a_block_has_no_unreachable_tail():
    source = """
    contract NoDeadCode {
        state value : int;

        function run(flag : bool) {
            if (flag) {
                value = 1;
            } else {
                value = 2;
            }
            value = 3;
        }
    }
    """
    validate_generated_source(source)
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "value = 1;" in optimized_source
    assert "value = 2;" in optimized_source
    assert "value = 3;" in optimized_source
    assert optimizer.optimizations == []
    validate_generated_source(optimized_source)


def test_repeated_numeric_folds_are_reported_once_per_ast_occurrence():
    program = parse_source(
        """
        contract RepeatedNumericFolds {
            state balance : int;
            function update() {
                balance = 1 + 2;
                balance = 1 + 2;
            }
        }
        """
    )
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert optimized_source.count("balance = 3;") == 2
    assert [item.rule_id for item in optimizer.optimizations] == [
        "OPT-007", "OPT-007",
    ]
    assert len(optimizer.optimizations) == 2
    validate_generated_source(optimized_source)


def test_unused_analysis_reports_without_deleting_interface_or_effectful_statements():
    source = """
    contract UnusedDiagnostics {
        state audit_total : int;

        function readValue() : int {
            return 4;
        }

        function update(unused_parameter : int) {
            int never_read = 1;
            int written = 2 + 1;
            written = readValue();
            audit_total = written;
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    assert "int never_read = 1;" in optimized_source
    assert "int written = 3;" in optimized_source
    assert "written = readValue();" in optimized_source
    assert "unused_parameter : int" in optimized_source
    warnings = "\n".join(optimizer.warnings)
    assert "Local variable 'never_read'" in warnings
    assert "Parameter 'unused_parameter'" in warnings
    assert "Initial value of local 'written'" in warnings
    assert "State variable 'audit_total' is not read" in warnings
    assert "OPT-007" in {item.rule_id for item in optimizer.optimizations}
    validate_generated_source(optimized_source)


@pytest.mark.parametrize(
    ("domain", "source", "ordered_fragments"),
    [
        (
            "banking",
            """
            contract BankingOptimizerOrder {
                state balance : int;
                function withdraw(amount : int) {
                    int known = 3;
                    int observed = known;
                    require(amount > 0);
                    require(amount <= balance);
                    balance = balance - amount;
                    balance = balance - amount;
                }
            }
            """,
            [
                "require((amount > 0));",
                "require((amount <= balance));",
                "balance = (balance - amount);",
                "balance = (balance - amount);",
            ],
        ),
        (
            "supply_chain",
            """
            contract SupplyOptimizerOrder {
                state status : string;
                state shipment_count : int;
                function dispatchShipment() {
                    int known = 3;
                    int observed = known;
                    require(status == "registered");
                    status = "dispatched";
                    shipment_count = shipment_count + 1;
                }
            }
            """,
            [
                'require((status == "registered"));',
                'status = "dispatched";',
                "shipment_count++;",
            ],
        ),
        (
            "voting",
            """
            contract VotingOptimizerOrder {
                state voting_open : bool;
                state eligible : bool;
                state has_voted : bool;
                state vote_count : int;
                function vote() {
                    int known = 3;
                    int observed = known;
                    require(voting_open == true);
                    require(eligible == true);
                    require(!has_voted);
                    has_voted = true;
                    vote_count = vote_count + 1;
                }
            }
            """,
            [
                "require((voting_open == true));",
                "require((eligible == true));",
                "require((!has_voted));",
                "has_voted = true;",
                "vote_count++;",
            ],
        ),
    ],
    ids=["banking", "supply-chain", "voting"],
)
def test_optimizer_pipeline_preserves_domain_guard_and_state_update_order(
    domain, source, ordered_fragments
):
    program = parse_source(source)
    original_analyzer = SemanticAnalyzer(program)
    with contextlib.redirect_stdout(io.StringIO()):
        assert original_analyzer.analyze(), original_analyzer.errors

    domain_analyzer = DomainAnalyzer(program, domain)
    domain_analyzer.analyze()
    assert domain_analyzer.issues == []

    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)
    assert "int observed = 3;" in optimized_source
    assert "OPT-024" in {item.rule_id for item in optimizer.optimizations}
    positions = [optimized_source.index(fragment) for fragment in ordered_fragments]
    assert positions == sorted(positions)

    optimized_program = validate_generated_source(optimized_source)
    optimized_domain = DomainAnalyzer(optimized_program, domain)
    optimized_domain.analyze()
    assert optimized_domain.issues == []


def test_optimizer_does_not_invent_or_reorder_input_multiplication_assignment():
    source = """
    contract BankTest {
        state balance : int;
        function withdraw(amount : int) {
            balance = balance * 2;
            balance = balance - amount;
            require(amount > 0);
        }
    }
    """
    program = parse_source(source)
    optimizer = Optimizer(program)
    optimizer.optimize()
    optimized_source = CodeGenerator().generate(program)

    multiplication = "balance = (balance << 1);"
    subtraction = "balance = (balance - amount);"
    assert optimized_source.count(multiplication) == 1
    assert optimized_source.count(subtraction) == 1
    assert optimized_source.index(multiplication) < optimized_source.index(subtraction)
    assert optimized_source.index(subtraction) < optimized_source.index(
        "require((amount > 0));"
    )
    assert "OPT-016" in {
        item.rule_id for item in optimizer.optimizations
    }
    validate_generated_source(optimized_source)
