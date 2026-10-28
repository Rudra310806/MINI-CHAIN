from io import BytesIO
import json
from pathlib import Path

import pytest

import app as app_module
from app import app


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    with app.test_client() as test_client:
        yield test_client


def upload(source, filename="contract.mc", domain="banking"):
    return {
        "domain": domain,
        "source_file": (BytesIO(source.encode("utf-8")), filename),
    }


VALID_BANK = """
contract Bank {
    state balance : int;
    function deposit(amount : int) {
        require(amount > 0);
        balance = balance + amount;
    }
}
"""


def test_analyze_endpoint_returns_pipeline_summary_and_optimized_source(client):
    response = client.post("/api/analyze", data=upload(VALID_BANK))

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is True
    assert result["contract_name"] == "Bank"
    assert result["filename"] == "contract.mc"
    assert result["optimized_code"] is not None
    assert result["summary"] == {
        "errors": 0,
        "domain_issues": 0,
        "optimizations": 0,
        "warnings": 0,
    }
    assert {
        "success", "contract_name", "domain", "filename", "stages", "errors",
        "domain_issues", "optimizations", "warnings", "optimized_code", "summary",
    }.issubset(result)
    assert result["lexical_report"]["status"] == "success"
    assert result["ast_report"]["status"] == "success"
    assert result["semantic_report"]["status"] == "success"
    assert [stage["name"] for stage in result["stages"]][-1] == "Optimized-source validation"
    assert all(stage["status"] == "success" for stage in result["stages"])
    json.dumps(result)


def test_editor_source_uses_existing_analysis_pipeline_and_selected_domain(client):
    source = """contract PastedContract {
    function value() : int { return 3; }
}"""

    # The paste editor submits text as a named source_file part, preserving the
    # existing multipart API and compiler pipeline.
    response = client.post(
        "/api/analyze",
        data=upload(source, filename="pasted_contract.mc", domain="voting"),
    )
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert result["domain"] == "voting"
    assert result["filename"] == "pasted_contract.mc"
    assert result["lexical_report"]["status"] == "success"
    assert result["ast_report"]["tree"]["contract"]["name"] == "PastedContract"
    assert result["semantic_report"]["status"] == "success"
    assert result["stages"][-1]["name"] == "Optimized-source validation"
    assert result["stages"][-1]["status"] == "success"


def test_empty_editor_source_is_rejected_by_existing_upload_contract(client):
    response = client.post(
        "/api/analyze",
        data={
            "domain": "banking",
            "source_file": (BytesIO(b""), "pasted_contract.mc"),
        },
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "The uploaded file is empty."}


def test_invalid_editor_source_returns_pipeline_diagnostics(client):
    source = "contract Broken { function run() {"
    response = client.post(
        "/api/analyze",
        data=upload(source, filename="pasted_contract.mc", domain="supply_chain"),
    )
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is False
    assert result["domain"] == "supply_chain"
    assert result["lexical_report"]["status"] == "success"
    assert result["ast_report"]["status"] == "failed"
    assert result["semantic_report"]["status"] == "not_run"
    assert result["errors"]
    assert any(stage["status"] == "failed" for stage in result["stages"])


def test_frontend_has_explicit_modes_and_builds_requests_from_only_the_active_source(client):
    response = client.get("/")
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="paste-mode-button"' in page
    assert 'id="upload-mode-button"' in page
    assert 'id="pasted-source"' in page
    assert 'id="source_file"' in page
    assert 'id="clear-pasted-source"' in page
    assert 'id="load-example-source"' in page
    assert 'id="paste-character-count"' in page
    assert 'if (inputMode === "paste")' in page
    assert 'if (!source.trim())' in page
    assert 'formData.append("source_file", requestSourceFile, requestFilename)' in page
    assert 'byId("source_file").disabled = pasteActive;' in page
    assert "new FormData(form)" not in page
    # Repair is bound to the successfully analyzed source/domain, not whichever
    # inactive input happens to remain in the form after a mode switch.
    assert 'repairFormData.append("domain", lastAnalyzedInput.domain)' in page
    assert 'lastAnalyzedInput.file' in page


def test_analyze_endpoint_returns_revalidated_constant_propagation_output(client):
    source = """
    contract OptimizedPropagationApi {
        function read() : int {
            int known = 5;
            return known;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "int known = 5;" in result["optimized_code"]
    assert "return 5;" in result["optimized_code"]
    assert any(
        item["rule_id"] == "OPT-024"
        for item in result["optimizations"]
    )
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    validation = result["stages"][-1]
    assert validation["name"] == "Optimized-source validation"
    assert validation["status"] == "success"


def test_analyze_endpoint_reports_integer_constant_fold_and_consistent_count(client):
    source = """
    contract Test {
        state balance : int;
        function calculate() {
            balance = 2 + 3;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "balance = 5;" in result["optimized_code"]
    assert "balance = (2 + 3);" not in result["optimized_code"]
    assert [item["rule_id"] for item in result["optimizations"]] == [
        "OPT-007",
    ]
    assert result["optimizations"][0]["message"] == (
        "Constant folding: 2 + 3 -> 5."
    )
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    optimization_stage = next(
        stage for stage in result["stages"]
        if stage["name"] == "Optimization & code generation"
    )
    assert optimization_stage["message"] == (
        "Generated optimized source with 1 optimization entry/entries."
    )
    assert result["stages"][-1]["status"] == "success"


def test_analyze_endpoint_returns_folded_division_and_modulo(client):
    source = """
    contract DivisionModuloApi {
        function exactDivision() : int {
            return 20 / 5;
        }

        function nonExactDivision() : int {
            return 7 / 2;
        }

        function remainder() : int {
            return 17 % 5;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "return 4;" in result["optimized_code"]
    assert "return 3;" in result["optimized_code"]
    assert "return 2;" in result["optimized_code"]
    assert [item["rule_id"] for item in result["optimizations"]] == [
        "OPT-007", "OPT-007", "OPT-007",
    ]
    assert [item["message"] for item in result["optimizations"]] == [
        "Constant folding: 20 / 5 -> 4.",
        "Constant folding: 7 / 2 -> 3.",
        "Constant folding: 17 % 5 -> 2.",
    ]
    assert result["summary"]["optimizations"] == 3
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    assert result["stages"][-1] == {
        "name": "Optimized-source validation",
        "status": "success",
        "message": "Generated source parsed and passed semantic analysis.",
    }


def test_analyze_endpoint_returns_folded_integer_shifts(client):
    source = """
    contract IntegerShiftApi {
        function left() : int {
            return 1 << 2;
        }

        function right() : int {
            return 9 >> 2;
        }

        function zeroCount() : int {
            return 5 << 0;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "return 4;" in result["optimized_code"]
    assert "return 2;" in result["optimized_code"]
    assert "return 5;" in result["optimized_code"]
    assert [item["rule_id"] for item in result["optimizations"]] == [
        "OPT-007", "OPT-007", "OPT-007",
    ]
    assert [item["message"] for item in result["optimizations"]] == [
        "Constant folding: 1 << 2 -> 4.",
        "Constant folding: 9 >> 2 -> 2.",
        "Constant folding: 5 << 0 -> 5.",
    ]
    assert result["summary"]["optimizations"] == 3
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    assert result["stages"][-1] == {
        "name": "Optimized-source validation",
        "status": "success",
        "message": "Generated source parsed and passed semantic analysis.",
    }


def test_analyze_endpoint_reports_integer_multiplication_strength_reduction(client):
    source = """
    contract StrengthReductionApi {
        function calculate(value : int) : int {
            return 16 * value;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "return (value << 4);" in result["optimized_code"]
    assert [item["rule_id"] for item in result["optimizations"]] == [
        "OPT-025",
    ]
    assert result["optimizations"][0]["message"] == (
        "Strength reduction: 16 * x -> x << 4."
    )
    assert result["summary"]["optimizations"] == 1
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    assert result["stages"][-1] == {
        "name": "Optimized-source validation",
        "status": "success",
        "message": "Generated source parsed and passed semantic analysis.",
    }


def test_analyze_endpoint_reports_guarded_division_to_shift_reduction(client):
    source = """
    contract GuardedDivisionApi {
        function calculate(value : int) : int {
            require(value >= 0);
            return value / 8;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "return (value >> 3);" in result["optimized_code"]
    assert [item["rule_id"] for item in result["optimizations"]] == [
        "OPT-026",
    ]
    assert result["optimizations"][0]["message"] == (
        "Strength reduction: value / 8 -> value >> 3 "
        "after a nonnegative require guard."
    )
    assert result["summary"]["optimizations"] == 1
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    assert result["stages"][-1] == {
        "name": "Optimized-source validation",
        "status": "success",
        "message": "Generated source parsed and passed semantic analysis.",
    }


def test_analyze_endpoint_accepts_prefix_and_postfix_updates_without_fake_optimization(
    client,
):
    source = """contract UpdateApi {
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

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "int previous = value++;" in result["optimized_code"]
    assert "++total;" in result["optimized_code"]
    assert "int current = --value;" in result["optimized_code"]
    assert "total--;" in result["optimized_code"]
    assert json.dumps(result["ast_report"]).count('"kind": "UpdateExpression"') == 4
    assert [token["type"] for token in result["lexical_report"]["tokens"]].count(
        "PLUS_PLUS"
    ) == 2
    assert [token["type"] for token in result["lexical_report"]["tokens"]].count(
        "MINUS_MINUS"
    ) == 2
    assert result["optimizations"] == []
    assert result["summary"]["optimizations"] == 0
    assert result["stages"][-1] == {
        "name": "Optimized-source validation",
        "status": "success",
        "message": "Generated source parsed and passed semantic analysis.",
    }


def test_analyze_endpoint_reports_increment_assignment_simplifications(client):
    source = """contract IncrementAssignmentApi {
        function adjust(value : int) : int {
            value = value + 1;
            value = 1 + value;
            value = value - 1;
            return value;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "value++;" in result["optimized_code"]
    assert result["optimized_code"].count("value++;") == 2
    assert "value--;" in result["optimized_code"]
    assert [item["rule_id"] for item in result["optimizations"]] == [
        "OPT-027", "OPT-027", "OPT-027",
    ]
    assert [item["message"] for item in result["optimizations"]] == [
        "Assignment simplification: value = value + 1 -> value++.",
        "Assignment simplification: value = 1 + value -> value++.",
        "Assignment simplification: value = value - 1 -> value--.",
    ]
    assert result["summary"]["optimizations"] == 3
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    assert result["stages"][-1] == {
        "name": "Optimized-source validation",
        "status": "success",
        "message": "Generated source parsed and passed semantic analysis.",
    }


def test_analyze_endpoint_runs_dce_for_both_terminating_boolean_branches(client):
    source = """contract BranchDeadCode {
        state result : int;

        function calculate(flag : bool) {
            if (flag) {
                return;
            } else {
                return;
            }

            result = 99;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert result["optimized_code"] is not None
    assert "result = 99;" not in result["optimized_code"]
    assert "return;" in result["optimized_code"]
    assert [item["rule_id"] for item in result["optimizations"]] == [
        "OPT-006",
    ]
    assert result["summary"]["optimizations"] == 1
    assert result["stages"][-1] == {
        "name": "Optimized-source validation",
        "status": "success",
        "message": "Generated source parsed and passed semantic analysis.",
    }


def test_analyze_endpoint_removes_constant_false_loop_and_validates_output(client):
    source = """contract FalseLoopDCE {
        state value : int;

        function run() {
            while (false) {
                value = 99;
            }
            value = 1;
        }
    }
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert "while (false)" not in result["optimized_code"]
    assert "value = 99;" not in result["optimized_code"]
    assert "value = 1;" in result["optimized_code"]
    assert [item["rule_id"] for item in result["optimizations"]] == [
        "OPT-005",
    ]
    assert result["summary"]["optimizations"] == 1
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    assert result["stages"][-1] == {
        "name": "Optimized-source validation",
        "status": "success",
        "message": "Generated source parsed and passed semantic analysis.",
    }


def test_analyze_endpoint_reports_the_invalid_boolean_parameter_order(client):
    # MiniChain declares parameters as `name : type`, not `type name`.
    source = """contract BranchDeadCode {
    state result : int;

    function calculate(bool flag) {
        if (flag) {
            return;
        } else {
            return;
        }

        result = 99;
    }
}"""

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is False
    assert result["optimized_code"] is None
    assert result["optimizations"] == []
    assert result["stages"][-1] == {
        "name": "Syntax analysis",
        "status": "failed",
        "message": "Expected parameter name at line 4, column 24",
    }
    assert result["errors"] == [
        "Expected parameter name at line 4, column 24",
    ]


def test_analyze_endpoint_withholds_source_when_generated_validation_fails(
    client, monkeypatch
):
    monkeypatch.setattr(
        app_module.CodeGenerator,
        "generate",
        lambda _self, _program: "not valid MiniChain",
    )

    response = client.post("/api/analyze", data=upload(VALID_BANK))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is False
    assert result["optimized_code"] is None
    assert result["stages"][-1]["name"] == "Optimized-source validation"
    assert result["stages"][-1]["status"] == "failed"


@pytest.mark.parametrize(
    ("literal", "expected_literal"),
    [
        ("100000000000000000000.0", "100000000000000000000.0"),
        ("0.0000001", "0.0000001"),
    ],
    ids=["large-float", "small-float"],
)
def test_analyze_endpoint_validates_float_literals_outside_plain_repr_range(
    client, literal, expected_literal
):
    source = f"""
    contract FloatFormatting {{
        function value() : float {{
            return {literal};
        }}
    }}
    """

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert all(stage["status"] == "success" for stage in result["stages"])
    assert f"return {expected_literal};" in result["optimized_code"]


def test_analyze_endpoint_serializes_tokens_ast_and_successful_symbols(client):
    source = """contract Reports {
    state balance : int;
    function read(value : int) : int { return value; }
}"""

    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["lexical_report"]["status"] == "success"
    function_token = next(
        token for token in result["lexical_report"]["tokens"]
        if token["value"] == "function"
    )
    assert function_token == {
        "type": "FUNCTION", "value": "function", "line": 3, "column": 5,
    }

    tree = result["ast_report"]["tree"]
    assert tree["kind"] == "Program"
    assert tree["contract"]["kind"] == "Contract"
    assert tree["contract"]["name"] == "Reports"
    assert tree["contract"]["functions"][0]["parameters"][0] == {
        "kind": "Parameter",
        "name": "value",
        "type": {"kind": "Type", "name": "int"},
    }

    symbols = result["semantic_report"]["symbols"]
    assert symbols["states"] == [{"name": "balance", "type": "int"}]
    assert symbols["functions"] == [{
        "name": "read",
        "parameters": [{"name": "value", "type": "int"}],
        "return_type": "int",
    }]
    json.dumps(result)


def test_flask_pipeline_handles_review_ready_long_contract(client):
    fixture_path = Path(__file__).parent / "fixtures" / "review_ready_bank.mc"
    source = fixture_path.read_text(encoding="utf-8")
    source_line_count = len(source.splitlines())

    assert 90 <= source_line_count <= 110

    response = client.post(
        "/api/analyze",
        data=upload(source, filename="review_ready_bank.mc"),
    )
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is True
    assert result["contract_name"] == "ReviewReadyBank"
    assert [stage["name"] for stage in result["stages"]] == [
        "Lexical analysis", "Syntax analysis", "Semantic analysis",
        "Domain analysis", "Optimization & code generation",
        "Optimized-source validation",
    ]
    assert all(stage["status"] == "success" for stage in result["stages"])

    lexical = result["lexical_report"]
    assert lexical["status"] == "success"
    assert len(lexical["tokens"]) > 300
    assert all(
        set(token) == {"type", "value", "line", "column"}
        and isinstance(token["line"], int)
        and isinstance(token["column"], int)
        for token in lexical["tokens"]
    )
    assert any(
        token["value"] == "countSteps" and token["line"] > 1
        for token in lexical["tokens"]
    )

    ast_report = result["ast_report"]
    assert ast_report["status"] == "success"
    assert ast_report["truncated"] is False

    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    ast_nodes = list(walk(ast_report["tree"]))
    assert ast_report["tree"]["kind"] == "Program"
    assert ast_report["tree"]["contract"]["kind"] == "Contract"
    assert ast_report["tree"]["contract"]["name"] == "ReviewReadyBank"
    assert [item["name"] for item in ast_report["tree"]["contract"]["states"]] == [
        "balance", "owner", "active", "daily_limit",
        "transaction_count", "last_amount",
    ]
    assert {
        "deposit", "withdraw", "changeOwner", "setDailyLimit", "setActive",
        "getBalance", "getOwner", "estimateCharge", "countSteps",
        "isWithinLimit", "recordAmount", "resetTransactionCount",
        "applyServiceFee", "canWithdraw", "remainingLimit", "setOwnerIfActive",
    } == {
        function["name"]
        for function in ast_report["tree"]["contract"]["functions"]
    }
    assert any(node["kind"] == "IfStatement" for node in ast_nodes)
    assert any(node["kind"] == "WhileStatement" for node in ast_nodes)
    assert any(
        node["kind"] == "BinaryExpression" and node.get("operator") == "*"
        for node in ast_nodes
    )
    # The AST report is the actual parsed input AST, captured before optimization.
    deposit = next(
        function
        for function in ast_report["tree"]["contract"]["functions"]
        if function["name"] == "deposit"
    )
    deposit_balance_update = next(
        statement
        for statement in deposit["body"]["statements"]
        if statement["kind"] == "Assignment"
        and statement["name"] == "balance"
    )
    assert deposit_balance_update["value"]["operator"] == "+"
    assert deposit_balance_update["value"]["right"] == {
        "kind": "Literal", "value": 0,
        "type": {"kind": "Type", "name": "int"},
    }
    assert deposit_balance_update["value"]["left"]["operator"] == "+"

    semantic = result["semantic_report"]
    assert semantic["status"] == "success"
    assert semantic["diagnostics"] == []
    assert semantic["symbols"]["states"] == [
        {"name": name, "type": type_name}
        for name, type_name in (
            ("balance", "int"), ("owner", "address"), ("active", "bool"),
            ("daily_limit", "int"), ("transaction_count", "int"),
            ("last_amount", "int"),
        )
    ]
    assert {item["name"] for item in semantic["symbols"]["functions"]} == {
        "deposit", "withdraw", "changeOwner", "setDailyLimit", "setActive",
        "getBalance", "getOwner", "estimateCharge", "countSteps",
        "isWithinLimit", "recordAmount", "resetTransactionCount",
        "applyServiceFee", "canWithdraw", "remainingLimit", "setOwnerIfActive",
    }

    # The fixture satisfies the currently recognized Banking patterns.
    assert result["domain_issues"] == []
    assert result["summary"]["domain_issues"] == 0

    # The report names the actual integer identity rewrite. No expression in
    # this fixture has two integer-literal +, -, or * operands to fold.
    assert any(
        item["rule_id"] == "OPT-008"
        and item["message"] == "Algebraic simplification: x + 0 -> x."
        for item in result["optimizations"]
    )
    assert result["summary"]["optimizations"] == len(result["optimizations"])
    assert "balance = (balance + amount);" in result["optimized_code"]
    assert "amount * rate" in result["optimized_code"]
    assert not any(
        item["rule_id"] in {"OPT-007", "OPT-015"}
        for item in result["optimizations"]
    )
    json.dumps(result)


def test_analyze_endpoint_preserves_tokens_when_syntax_fails(client):
    response = client.post(
        "/api/analyze",
        data=upload("contract Broken { function f() { return; }")
    )
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is False
    assert result["lexical_report"]["status"] == "success"
    assert result["lexical_report"]["tokens"]
    assert result["ast_report"]["status"] == "failed"
    assert result["semantic_report"]["status"] == "not_run"


def test_analyze_endpoint_reports_semantic_diagnostics_and_withholds_incomplete_symbols(client):
    source = "contract Broken { function f() : int { return missing; } }"
    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is False
    assert result["ast_report"]["status"] == "success"
    assert result["semantic_report"]["status"] == "failed"
    assert result["semantic_report"]["symbols"] is None
    assert any(
        "Undefined variable 'missing'." in item
        for item in result["semantic_report"]["diagnostics"]
    )


def test_analyze_endpoint_does_not_optimize_semantically_invalid_code_after_return(client):
    source = """
    contract InvalidUnreachableCode {
        state balance : int;
        function calculate() {
            return;
            balance = missing;
        }
    }
    """
    response = client.post("/api/analyze", data=upload(source))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is False
    assert result["optimized_code"] is None
    assert result["optimizations"] == []
    assert result["semantic_report"]["status"] == "failed"
    assert any(
        "Undefined variable 'missing'." in item
        for item in result["semantic_report"]["diagnostics"]
    )
    assert result["stages"][-1]["name"] == "Semantic analysis"
    assert result["stages"][-1]["status"] == "failed"


def test_semantic_failure_without_analyzer_diagnostics_is_not_reported_as_clear(client, monkeypatch):
    class SilentFailureAnalyzer:
        def __init__(self, _program):
            self.errors = []

        def analyze(self):
            return False

    monkeypatch.setattr(app_module, "SemanticAnalyzer", SilentFailureAnalyzer)
    response = client.post("/api/analyze", data=upload(VALID_BANK))
    result = response.get_json()

    assert response.status_code == 200
    assert result["success"] is False
    assert result["semantic_report"]["status"] == "failed"
    assert result["semantic_report"]["diagnostics"] == [
        "Semantic analysis failed; inspect analyzer output."
    ]
    assert result["errors"] == result["semantic_report"]["diagnostics"]


def test_lexical_failure_marks_unavailable_reports_and_keeps_legacy_fields(client):
    response = client.post("/api/analyze", data=upload("@"))
    result = response.get_json()

    assert result["lexical_report"]["status"] == "failed"
    assert result["lexical_report"]["tokens"] == []
    assert result["ast_report"]["status"] == "not_run"
    assert result["semantic_report"]["status"] == "not_run"
    assert result["errors"] == result["lexical_report"]["diagnostics"]
    assert result["summary"]["errors"] == len(result["errors"])


def test_analyze_endpoint_reports_lexical_failure_in_response(client):
    response = client.post("/api/analyze", data=upload("@"))

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is False
    assert result["stages"][0]["name"] == "Lexical analysis"
    assert result["stages"][0]["status"] == "failed"
    assert "Unexpected character '@'" in result["errors"][0]


def test_repair_endpoint_applies_detected_banking_guards_and_reanalyzes(client):
    source = """
    contract Bank {
        state balance : int;
        function withdraw(amount : int) {
            balance = balance - amount;
        }
    }
    """

    response = client.post("/api/repair", data=upload(source))

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is True
    assert {item["rule_id"] for item in result["applied"]} == {
        "BANK-001",
        "BANK-002",
    }
    assert result["skipped"] == []
    assert result["rejected"] == []
    assert "require(amount > 0);" in result["repaired_code"]
    assert "require(amount <= balance);" in result["repaired_code"]
    assert result["analysis_after"]["success"] is True
    assert result["analysis_after"]["domain_issues"] == []


def test_repair_endpoint_rejects_source_that_does_not_reach_domain_analysis(client):
    response = client.post("/api/repair", data=upload("@"))

    assert response.status_code == 422
    result = response.get_json()
    assert "must pass parsing and semantic analysis" in result["error"]
    assert result["analysis_before"]["stages"][0]["status"] == "failed"


def test_repair_endpoint_preserves_mixed_case_amount_parameter(client):
    source = """
    contract Bank {
        state balance : int;
        function withdraw(Amount : int) {
            balance = balance - Amount;
        }
    }
    """

    response = client.post("/api/repair", data=upload(source))

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is True
    assert {item["rule_id"] for item in result["applied"]} == {
        "BANK-001",
        "BANK-002",
    }
    assert "require(Amount > 0);" in result["repaired_code"]
    assert "require(Amount <= balance);" in result["repaired_code"]
    assert "require(amount > 0);" not in result["repaired_code"]
    assert result["analysis_after"]["success"] is True
    assert result["analysis_after"]["errors"] == []
    assert result["rejected"] == []


def test_repair_endpoint_keeps_unsupported_banking_issues_skipped(client):
    source = """
    contract Bank {
        state balance : int;
        function withdraw() {
            balance = balance - 1;
        }
    }
    """

    response = client.post("/api/repair", data=upload(source))

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is True
    assert result["applied"] == []
    assert {item["rule_id"] for item in result["skipped"]} == {
        "BANK-001",
        "BANK-002",
        "BANK-003",
    }
    assert result["repaired_code"] == source
    assert {item["rule_id"] for item in result["analysis_after"]["domain_issues"]} == {
        "BANK-001",
        "BANK-002",
        "BANK-003",
    }
    assert result["rejected"] == []


def test_failed_repair_candidate_returns_original_source(client, monkeypatch):
    source = """
    contract Bank {
        state balance : int;
        function withdraw(amount : int) {
            balance = balance - amount;
        }
    }
    """

    invalid_candidate = source.replace(
        "balance = balance - amount;",
        "missing = amount;",
    )

    def repair_with_invalid_candidate(original, _domain, _issues):
        assert original == source
        return invalid_candidate, [{
            "rule_id": "BANK-001",
            "function": "withdraw",
            "changes": ["missing = amount;"],
        }], []

    monkeypatch.setattr(app_module, "repair_source", repair_with_invalid_candidate)

    response = client.post("/api/repair", data=upload(source))

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is False
    assert result["message"] == (
        "Repair candidate failed compiler revalidation; original source retained."
    )
    assert result["repaired_code"] == source
    assert "missing = amount;" not in result["repaired_code"]
    assert result["applied"] == []
    assert result["skipped"] == []
    assert result["rejected"][0]["rule_id"] == "BANK-001"
    assert "original source retained" in result["rejected"][0]["reason"]
    assert "Undefined variable 'missing'." in result["rejected"][0]["reason"]
    assert result["analysis_after"]["success"] is True
    assert result["analysis_after"]["errors"] == []
    assert "BANK-001" in {
        item["rule_id"] for item in result["analysis_after"]["domain_issues"]
    }


def test_repair_endpoint_rejects_candidate_when_target_finding_remains(
    client, monkeypatch
):
    source = """contract Bank {
        state balance : int;
        function withdraw(amount : int) {
            require(amount <= balance);
            balance = balance - amount;
        }
    }"""

    def repair_without_fix(original, _domain, _issues):
        return original, [{
            "rule_id": "BANK-001",
            "function": "withdraw",
            "changes": ["require(amount > 0);"],
        }], []

    monkeypatch.setattr(app_module, "repair_source", repair_without_fix)
    response = client.post("/api/repair", data=upload(source))

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is False
    assert result["applied"] == []
    assert result["skipped"] == []
    assert result["rejected"][0]["rule_id"] == "BANK-001"
    assert "targeted domain finding remained" in result["rejected"][0]["reason"]
    assert result["repaired_code"] == source
    assert result["analysis_after"]["success"] is True
    assert "BANK-001" in {
        item["rule_id"] for item in result["analysis_after"]["domain_issues"]
    }


@pytest.mark.parametrize(
    ("domain", "source", "rule_id", "expected_change"),
    [
        (
            "banking",
            """contract Bank { state balance : int; function withdraw(amount : int) {
                require(amount <= balance); balance = balance - amount;
            } }""",
            "BANK-001",
            "require(amount > 0);",
        ),
        (
            "banking",
            """contract Bank { state balance : int; function withdraw(amount : int) {
                require(amount > 0); balance = balance - amount;
            } }""",
            "BANK-002",
            "require(amount <= balance);",
        ),
        (
            "banking",
            """contract Bank { state balance : int; function deposit(amount : int) {
                balance = balance + amount;
            } }""",
            "BANK-004",
            "require(amount > 0);",
        ),
        (
            "banking",
            """contract Bank { state balance : int; function transfer(amount : int) {
                require(amount <= balance); balance = balance - amount;
            } }""",
            "BANK-006",
            "require(amount > 0);",
        ),
        (
            "banking",
            """contract Bank { state balance : int; function transfer(amount : int) {
                require(amount > 0); balance = balance - amount;
            } }""",
            "BANK-007",
            "require(amount <= balance);",
        ),
        (
            "supply_chain",
            """contract SupplyChain { state status : string;
                function registerProduct() { }
            }""",
            "SC-001",
            'status = "registered";',
        ),
        (
            "supply_chain",
            """contract SupplyChain { state status : string;
                function dispatchProduct() { status = "dispatched"; }
            }""",
            "SC-002",
            'require(status == "registered");',
        ),
        (
            "supply_chain",
            """contract SupplyChain { state status : string;
                function deliverProduct() { status = "delivered"; }
            }""",
            "SC-003",
            'require(status == "dispatched");',
        ),
        (
            "voting",
            """contract Governance {
                state voting_open : bool; state eligible : bool;
                state has_voted : bool; state vote_count : int;
                function vote() {
                    require(eligible); require(!has_voted);
                    has_voted = true; vote_count = vote_count + 1;
                }
            }""",
            "VOTE-001",
            "require(voting_open);",
        ),
        (
            "voting",
            """contract Governance {
                state voting_open : bool; state eligible : bool;
                state has_voted : bool; state vote_count : int;
                function vote() {
                    require(voting_open); require(!has_voted);
                    has_voted = true; vote_count = vote_count + 1;
                }
            }""",
            "VOTE-002",
            "require(eligible);",
        ),
        (
            "voting",
            """contract Governance {
                state voting_open : bool; state eligible : bool;
                state has_voted : bool; state vote_count : int;
                function vote() {
                    require(voting_open); require(eligible);
                    has_voted = true; vote_count = vote_count + 1;
                }
            }""",
            "VOTE-003",
            "require(!has_voted);",
        ),
    ],
    ids=[
        "bank-001", "bank-002", "bank-004", "bank-006", "bank-007",
        "sc-001", "sc-002", "sc-003", "vote-001", "vote-002", "vote-003",
    ],
)
def test_existing_supported_repairs_remain_revalidated(
    client, domain, source, rule_id, expected_change
):
    response = client.post("/api/repair", data=upload(source, domain=domain))

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is True
    assert rule_id in {item["rule_id"] for item in result["applied"]}
    assert expected_change in result["repaired_code"]
    assert result["rejected"] == []
    assert result["analysis_after"]["success"] is True
    assert rule_id not in {
        item["rule_id"] for item in result["analysis_after"]["domain_issues"]
    }


def test_bank_010_moves_only_adjacent_matching_guard_and_is_idempotent(client):
    source = """contract Bank {
        state balance : int;
        function withdraw(Amount : int, enabled : bool) {
            require(Amount <= balance);
            if (enabled) {
                balance = balance - Amount;
                require(Amount > 0);
            }
        }
        function transfer(amount : int) { }
    }"""

    before = client.post("/api/analyze", data=upload(source)).get_json()
    assert "BANK-010" in {
        item["rule_id"] for item in before["domain_issues"]
    }
    first = client.post("/api/repair", data=upload(source)).get_json()

    assert first["success"] is True
    assert "BANK-010" in {item["rule_id"] for item in first["applied"]}
    assert "require(Amount > 0);\n                balance = balance - Amount;" in first[
        "repaired_code"
    ]
    assert "require(amount > 0);" in first["repaired_code"]
    assert first["analysis_after"]["success"] is True
    remaining = {
        item["rule_id"] for item in first["analysis_after"]["domain_issues"]
    }
    assert "BANK-010" not in remaining
    assert "BANK-008" in remaining
    assert first["analysis_after"]["errors"] == []
    assert {
        stage["name"]
        for stage in first["analysis_after"]["stages"]
        if stage["status"] == "success"
    } >= {"Lexical analysis", "Syntax analysis", "Semantic analysis"}

    second = client.post(
        "/api/repair", data=upload(first["repaired_code"])
    ).get_json()
    assert second["success"] is True
    assert second["applied"] == []
    assert second["repaired_code"] == first["repaired_code"]


def test_sc_009_moves_adjacent_prior_status_guard_and_is_idempotent(client):
    source = """contract SupplyChain {
        state Shipment_Status : string;
        function dispatchShipment() {
            Shipment_Status = "dispatched";
            require(Shipment_Status == "registered");
        }
        function deliverProduct() { }
    }"""

    before = client.post(
        "/api/analyze", data=upload(source, domain="supply_chain")
    ).get_json()
    assert "SC-009" in {
        item["rule_id"] for item in before["domain_issues"]
    }
    first = client.post(
        "/api/repair", data=upload(source, domain="supply_chain")
    ).get_json()

    assert first["success"] is True
    assert "SC-009" in {item["rule_id"] for item in first["applied"]}
    assert (
        'require(Shipment_Status == "registered");\n'
        '            Shipment_Status = "dispatched";'
    ) in first["repaired_code"]
    assert first["analysis_after"]["success"] is True
    remaining = {
        item["rule_id"] for item in first["analysis_after"]["domain_issues"]
    }
    assert "SC-009" not in remaining
    assert "SC-006" in remaining
    assert first["analysis_after"]["errors"] == []
    assert {
        stage["name"]
        for stage in first["analysis_after"]["stages"]
        if stage["status"] == "success"
    } >= {"Lexical analysis", "Syntax analysis", "Semantic analysis"}

    second = client.post(
        "/api/repair",
        data=upload(first["repaired_code"], domain="supply_chain"),
    ).get_json()
    assert second["success"] is True
    assert second["applied"] == []
    assert second["repaired_code"] == first["repaired_code"]


@pytest.mark.parametrize(
    ("domain", "source", "rule_id", "reason_fragment"),
    [
        (
            "banking",
            """contract Bank {
                state balance : int; state fee : int;
                function withdraw(amount : int, enabled : bool) {
                    require(amount <= balance);
                    if (enabled) {
                        balance = balance - amount;
                        fee = fee + 1;
                        require(amount > 0);
                    }
                }
            }""",
            "BANK-010",
            "not a unique, adjacent pair",
        ),
        (
            "supply_chain",
            """contract SupplyChain {
                state status : string; state event_count : int;
                function dispatchProduct() {
                    status = "dispatched";
                    event_count = event_count + 1;
                    require(status == "registered");
                }
            }""",
            "SC-009",
            "not a unique adjacent top-level pair",
        ),
    ],
    ids=["bank-crosses-unrelated-statement", "supply-chain-crosses-unrelated-statement"],
)
def test_order_repairs_skip_ambiguous_statement_movement(
    client, domain, source, rule_id, reason_fragment
):
    result = client.post(
        "/api/repair", data=upload(source, domain=domain)
    ).get_json()

    assert result["success"] is True
    assert result["repaired_code"] == source
    assert result["applied"] == []
    assert [item["rule_id"] for item in result["skipped"]] == [rule_id]
    assert reason_fragment in result["skipped"][0]["reason"]
    assert result["analysis_after"]["success"] is True
    assert rule_id in {
        item["rule_id"] for item in result["analysis_after"]["domain_issues"]
    }


@pytest.mark.parametrize(
    ("domain", "source", "rule_id"),
    [
        (
            "voting",
            """
            contract Governance {
                state voting_open : bool;
                state eligible : bool;
                state has_voted : bool;
                state vote_count : int;
                function vote() {
                    require(voting_open);
                    require(!eligible);
                    require(!has_voted);
                    has_voted = true;
                    vote_count = vote_count + 1;
                }
            }
            """,
            "VOTE-006",
        ),
        (
            "voting",
            """
            contract Governance {
                state voting_open : bool;
                state eligible : bool;
                state has_voted : bool;
                state vote_count : int;
                function vote() {
                    require(!voting_open);
                    require(eligible);
                    require(!has_voted);
                    has_voted = true;
                    vote_count = vote_count + 1;
                }
            }
            """,
            "VOTE-007",
        ),
    ],
    ids=["vote-eligibility", "vote-period"],
)
def test_repair_api_explicitly_skips_new_rules_without_safe_repairs(
    client, domain, source, rule_id
):
    response = client.post(
        "/api/repair",
        data=upload(source, domain=domain),
    )

    assert response.status_code == 200
    result = response.get_json()
    assert result["success"] is True
    assert result["applied"] == []
    assert [item["rule_id"] for item in result["skipped"]] == [rule_id]
    assert "Automatic repair is unsupported" in result["skipped"][0]["reason"]
    assert "explicit policy" in result["skipped"][0]["reason"]
    assert result["repaired_code"] == source
    assert result["rejected"] == []
    assert result["analysis_after"]["success"] is True
    assert [
        item["rule_id"] for item in result["analysis_after"]["domain_issues"]
    ] == [rule_id]


def test_upload_validation_errors_keep_existing_api_status(client):
    response = client.post(
        "/api/analyze",
        data=upload(VALID_BANK, filename="contract.py"),
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Upload a .mc or .txt source file."}


def test_healthcare_domain_is_not_available_in_the_flask_selector_or_api(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b'value="healthcare"' not in response.data

    source = """
    contract Example { function run() { return; } }
    """
    response = client.post(
        "/api/analyze",
        data=upload(source, filename="records.mc", domain="healthcare"),
    )
    repair_response = client.post(
        "/api/repair",
        data=upload(source, filename="records.mc", domain="healthcare"),
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Please select a supported domain."}
    assert repair_response.status_code == 400
    assert repair_response.get_json() == {
        "error": "Please select a supported domain."
    }
