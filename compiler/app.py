import contextlib
import io
from dataclasses import fields, is_dataclass
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer
from domain_analyzer import DomainAnalyzer
from optimizer import Optimizer
from codegen import CodeGenerator
from repair import repair_source
from ast_nodes import ASTNode

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mc", ".txt"}
VALID_DOMAINS = {"banking", "supply_chain", "voting"}
AST_REPORT_NODE_LIMIT = 20000
AST_REPORT_DEPTH_LIMIT = 100
_AST_OMITTED = object()


def stage(name, status, message):
    return {"name": name, "status": status, "message": message}


def parse_source(source):
    return Parser(Lexer(source).tokenize()).parse()


def run_semantic(program):
    ok, errors, _analyzer = run_semantic_with_analyzer(program)
    return ok, errors


def run_semantic_with_analyzer(program):
    analyzer = SemanticAnalyzer(program)
    with contextlib.redirect_stdout(io.StringIO()):
        ok = analyzer.analyze()
    errors = [str(item) for item in getattr(analyzer, "errors", [])]
    return ok, errors, analyzer


def serialize_ast(root):
    """Serialize only declared AST dataclass fields into JSON-safe values."""
    state = {"nodes": 0, "truncated": False}

    def visit(value, depth=0):
        if value is None or type(value) in (str, int, float, bool):
            return value

        if isinstance(value, list):
            serialized = []
            for item in value:
                child = visit(item, depth)
                if child is _AST_OMITTED:
                    break
                serialized.append(child)
            return serialized

        if isinstance(value, ASTNode) and is_dataclass(value):
            if (
                state["nodes"] >= AST_REPORT_NODE_LIMIT
                or depth >= AST_REPORT_DEPTH_LIMIT
            ):
                state["truncated"] = True
                return _AST_OMITTED

            state["nodes"] += 1
            node = {"kind": type(value).__name__}
            for item in fields(value):
                child = visit(getattr(value, item.name), depth + 1)
                if child is not _AST_OMITTED:
                    node[item.name] = child
            return node

        raise TypeError(f"Unsupported AST report value: {type(value).__name__}")

    return visit(root), state["truncated"]


def semantic_report(analyzer, success, diagnostics):
    symbols = None
    if success:
        symbols = {
            "states": [
                {"name": name, "type": symbol_type.name}
                for name, symbol_type in analyzer.global_symbols.items()
            ],
            "functions": [
                {
                    "name": name,
                    "parameters": [
                        {"name": parameter.name, "type": parameter.type.name}
                        for parameter in function.parameters
                    ],
                    "return_type": (
                        function.return_type.name
                        if function.return_type is not None
                        else "void"
                    ),
                }
                for name, function in analyzer.functions.items()
            ],
        }

    return {
        "status": "success" if success else "failed",
        "diagnostics": diagnostics,
        "symbols": symbols,
    }


def issue_dict(issue):
    return {
        "rule_id": getattr(issue, "rule_id", ""),
        "severity": getattr(issue, "severity", "WARNING"),
        "function": getattr(issue, "function", None),
        "message": getattr(issue, "message", str(issue)),
        "display": str(issue),
    }


def finish(result):
    result["summary"] = {
        "errors": len(result["errors"]),
        "domain_issues": len(result["domain_issues"]),
        "optimizations": len(result["optimizations"]),
        "warnings": len(result["warnings"]),
    }
    return result


def analyze_source(source, domain, filename=None, include_reports=True):
    result = {
        "success": False, "contract_name": None, "domain": domain,
        "filename": filename, "stages": [], "errors": [],
        "domain_issues": [], "optimizations": [], "warnings": [],
        "optimized_code": None, "summary": {},
    }
    if include_reports:
        result.update({
            "lexical_report": {
                "status": "not_run", "tokens": [], "diagnostics": [],
            },
            "ast_report": {
                "status": "not_run", "tree": None,
                "truncated": False, "diagnostics": [],
            },
            "semantic_report": {
                "status": "not_run", "diagnostics": [], "symbols": None,
            },
        })
    stages = result["stages"]

    try:
        tokens = Lexer(source).tokenize()
        if include_reports:
            result["lexical_report"] = {
                "status": "success",
                "tokens": [
                    {
                        "type": token.type.name,
                        "value": token.value,
                        "line": token.line,
                        "column": token.column,
                    }
                    for token in tokens
                ],
                "diagnostics": [],
            }
        stages.append(stage("Lexical analysis", "success",
                            f"Tokenization successful: {max(0, len(tokens) - 1)} tokens generated."))
    except Exception as exc:
        if include_reports:
            result["lexical_report"] = {
                "status": "failed", "tokens": [], "diagnostics": [str(exc)],
            }
        stages.append(stage("Lexical analysis", "failed", str(exc)))
        result["errors"].append(str(exc))
        return finish(result)

    try:
        program = Parser(tokens).parse()
        result["contract_name"] = program.contract.name
        if include_reports:
            try:
                tree, truncated = serialize_ast(program)
                result["ast_report"] = {
                    "status": "success",
                    "tree": tree,
                    "truncated": truncated,
                    "diagnostics": [],
                }
            except Exception as exc:
                result["ast_report"] = {
                    "status": "failed", "tree": None,
                    "truncated": False, "diagnostics": [str(exc)],
                }
        stages.append(stage("Syntax analysis", "success", "Parsing successful; AST created."))
    except Exception as exc:
        if include_reports:
            result["ast_report"] = {
                "status": "failed", "tree": None,
                "truncated": False, "diagnostics": [str(exc)],
            }
        stages.append(stage("Syntax analysis", "failed", str(exc)))
        result["errors"].append(str(exc))
        return finish(result)

    try:
        semantic_ok, semantic_errors, analyzer = run_semantic_with_analyzer(program)
        if not semantic_ok and not semantic_errors:
            semantic_errors = ["Semantic analysis failed; inspect analyzer output."]
        if include_reports:
            result["semantic_report"] = semantic_report(
                analyzer, semantic_ok, semantic_errors
            )
    except Exception as exc:
        if include_reports:
            result["semantic_report"] = {
                "status": "failed", "diagnostics": [str(exc)], "symbols": None,
            }
        stages.append(stage("Semantic analysis", "failed", str(exc)))
        result["errors"].append(str(exc))
        return finish(result)

    if not semantic_ok:
        result["errors"].extend(semantic_errors)
        stages.append(stage("Semantic analysis", "failed",
                            f"{len(semantic_errors)} semantic error(s) found."))
        return finish(result)
    stages.append(stage("Semantic analysis", "success", "No semantic errors detected."))

    try:
        domain_analyzer = DomainAnalyzer(program, domain)
        domain_analyzer.analyze()
        result["domain_issues"] = [
            issue_dict(issue) for issue in getattr(domain_analyzer, "issues", [])
        ]
        stages.append(stage("Domain analysis", "success",
                            f"Completed {domain.replace('_', ' ')} analysis; "
                            f"{len(result['domain_issues'])} issue(s) found."))
    except Exception as exc:
        stages.append(stage("Domain analysis", "failed", str(exc)))
        result["errors"].append(str(exc))
        return finish(result)

    try:
        optimizer = Optimizer(program)
        optimizer.optimize()
        result["optimizations"] = [
            {"rule_id": getattr(item, "rule_id", ""),
             "message": getattr(item, "message", str(item)),
             "display": str(item)}
            for item in optimizer.optimizations
        ]
        result["warnings"] = [str(item) for item in optimizer.warnings]
        optimized_source = CodeGenerator().generate(program)
        stages.append(stage("Optimization & code generation", "success",
                            f"Generated optimized source with "
                            f"{len(result['optimizations'])} optimization entry/entries."))
    except Exception as exc:
        stages.append(stage("Optimization & code generation", "failed", str(exc)))
        result["errors"].append(str(exc))
        return finish(result)

    # Validate the exact source that will be returned to the UI.
    try:
        optimized_program = parse_source(optimized_source)
        optimized_ok, optimized_errors = run_semantic(optimized_program)
        if not optimized_ok:
            raise ValueError("; ".join(optimized_errors) or "semantic validation failed")
        stages.append(stage("Optimized-source validation", "success",
                            "Generated source parsed and passed semantic analysis."))
    except Exception as exc:
        stages.append(stage("Optimized-source validation", "failed", str(exc)))
        result["errors"].append(f"Optimized source failed validation: {exc}")
        return finish(result)

    result["optimized_code"] = optimized_source
    result["success"] = True
    return finish(result)


def uploaded_source():
    uploaded = request.files.get("source_file")
    domain = (request.form.get("domain") or "banking").strip().lower()
    if domain not in VALID_DOMAINS:
        return None, None, None, ("Please select a supported domain.", 400)
    if uploaded is None or not uploaded.filename:
        return None, None, None, ("Choose a MiniChain source file first.", 400)

    filename = secure_filename(uploaded.filename)
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        return None, None, None, ("Upload a .mc or .txt source file.", 400)
    try:
        raw = uploaded.read()
        if not raw:
            return None, None, None, ("The uploaded file is empty.", 400)
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, None, None, ("The source file must be UTF-8 text.", 400)
    return source, domain, filename, None


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/analyze")
def api_analyze():
    source, domain, filename, error = uploaded_source()
    if error:
        return jsonify({"error": error[0]}), error[1]
    return jsonify(analyze_source(source, domain, filename))


@app.post("/api/repair")
def api_repair():
    source, domain, filename, error = uploaded_source()
    if error:
        return jsonify({"error": error[0]}), error[1]

    before = analyze_source(source, domain, filename, include_reports=False)
    domain_stage_ok = any(
        item["name"] == "Domain analysis" and item["status"] == "success"
        for item in before["stages"]
    )
    if not domain_stage_ok:
        return jsonify({
            "error": "Source must pass parsing and semantic analysis before repair.",
            "analysis_before": before,
        }), 422

    # repair_source expects dictionaries; normalize analyzer issues before passing them.
    repaired, applied, skipped = repair_source(source, domain, before["domain_issues"])
    after = analyze_source(repaired, domain, filename, include_reports=False)
    rejected = []
    message = "Repair pass completed. Review every change and re-analysis."
    if not after["success"]:
        details = "; ".join(after["errors"])
        if not details:
            details = "; ".join(
                f"{item['name']}: {item['message']}"
                for item in after["stages"]
                if item["status"] == "failed"
            )
        reason = "Candidate failed compiler revalidation; original source retained."
        if details:
            reason += f" {details}"

        rejected.extend({**item, "reason": reason} for item in applied)
        applied = []
        repaired = source
        after = analyze_source(source, domain, filename, include_reports=False)
        message = "Repair candidate failed compiler revalidation; original source retained."
    else:
        remaining = {
            (item.get("rule_id", ""), item.get("function"))
            for item in after["domain_issues"]
        }
        unresolved = [
            item for item in applied
            if (item.get("rule_id", ""), item.get("function")) in remaining
        ]
        if unresolved:
            reason = (
                "Candidate passed compiler validation but its targeted domain "
                "finding remained after reanalysis; original source retained."
            )
            rejected.extend({**item, "reason": reason} for item in applied)
            applied = []
            repaired = source
            after = analyze_source(source, domain, filename, include_reports=False)
            message = (
                "Repair candidate rejected because a targeted domain finding "
                "remained after reanalysis; original source retained."
            )

    return jsonify({
        "success": after["success"] and not rejected,
        "filename": filename,
        "message": message,
        "applied": applied,
        "skipped": skipped,
        "rejected": rejected,
        "repaired_code": repaired,
        "analysis_after": after,
    })


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "File too large. Maximum upload size is 1 MB."}), 413


if __name__ == "__main__":
    app.run(debug=True,port = 5001)
