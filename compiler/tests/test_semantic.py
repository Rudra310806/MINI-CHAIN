import contextlib
import io

import pytest

from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer


def analyze_source(source):
    program = Parser(Lexer(source).tokenize()).parse()
    analyzer = SemanticAnalyzer(program)
    with contextlib.redirect_stdout(io.StringIO()):
        result = analyzer.analyze()
    return result, analyzer.errors


@pytest.mark.parametrize(
    ("body", "expected_error"),
    [
        ("return missing;", "Undefined variable 'missing'."),
        (
            "int value = true;",
            "Cannot initialize variable 'value' of type 'int' with type 'bool'.",
        ),
        (
            "take();",
            "Function 'take' expects 1 argument(s), but got 0.",
        ),
        (
            "return true;",
            "expects return type 'int', but got 'bool'.",
        ),
    ],
)
def test_semantic_analyzer_reports_expected_diagnostics(body, expected_error):
    source = f"""
    contract Semantic {{
        function take(value : int) {{ return; }}
        function check() : int {{ {body} }}
    }}
    """

    result, errors = analyze_source(source)

    assert result is False
    assert any(expected_error in error for error in errors)


def test_semantic_analyzer_reports_duplicate_state_and_function_names():
    source = """
    contract Duplicates {
        state value : int;
        state value : int;
        function run() { return; }
        function run() { return; }
    }
    """

    result, errors = analyze_source(source)

    assert result is False
    assert any("Duplicate state variable 'value'." in error for error in errors)
    assert any("Duplicate function 'run'." in error for error in errors)


def test_semantic_analyzer_accepts_well_typed_source():
    source = """
    contract Valid {
        state total : int;
        function add(value : int) : int {
            int next = value + 1;
            total = total + next;
            return next;
        }
    }
    """

    result, errors = analyze_source(source)

    assert result is True
    assert errors == []


def test_semantic_analyzer_accepts_integer_updates_on_state_locals_and_parameters():
    source = """
    contract IntegerUpdates {
        state total : int;

        function adjust(value : int) : int {
            int local = value;
            int old_value = local++;
            ++total;
            --value;
            return old_value + local;
        }
    }
    """

    result, errors = analyze_source(source)

    assert result is True
    assert errors == []


@pytest.mark.parametrize(
    ("declaration", "expression", "expected_type"),
    [
        ("float value = 1.0;", "value++", "float"),
        ("bool value = true;", "--value", "bool"),
    ],
)
def test_semantic_analyzer_rejects_updates_to_non_integer_identifiers(
    declaration, expression, expected_type
):
    source = f"""
    contract InvalidUpdateType {{
        function run() {{
            {declaration}
            {expression};
        }}
    }}
    """

    result, errors = analyze_source(source)

    assert result is False
    assert any(
        f"requires an 'int' identifier" in error
        and f"has type '{expected_type}'" in error
        for error in errors
    )


def test_semantic_analyzer_rejects_update_of_undefined_identifier():
    result, errors = analyze_source(
        "contract UndefinedUpdate { function run() { missing++; } }"
    )

    assert result is False
    assert errors == ["Undefined variable 'missing'."]
