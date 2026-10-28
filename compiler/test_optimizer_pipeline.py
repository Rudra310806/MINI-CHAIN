from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer
from optimizer import Optimizer
from codegen import CodeGenerator


SOURCE = """
contract OptimizerTest {
    state balance : int;

    function calculate(amount : int) : int {
        int doubled = amount * 2;
        int simplified = amount + 0;
        int constant = 3 * 4;

        if (true) {
            balance = balance + doubled;
        } else {
            balance = balance + 999;
        }

        return simplified + constant;
    }
}
"""


def parse_source(source):
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def main():
    print("=" * 60)
    print("MINICHAIN OPTIMIZER PIPELINE TEST")
    print("=" * 60)

    # 1. Parse the original source
    print("\n[1] Parsing original source...")
    program = parse_source(SOURCE)
    print("PASS: Original source parsed.")

    # 2. Validate original semantics
    print("\n[2] Checking original semantics...")
    original_analyzer = SemanticAnalyzer(program)
    if not original_analyzer.analyze():
        raise SystemExit("FAIL: Original semantic analysis failed.")
    print("PASS: Original semantic analysis passed.")

    # 3. Optimize the AST
    print("\n[3] Optimizing AST...")
    optimizer = Optimizer(program)
    optimizer.optimize()
    print("PASS: Optimizer completed.")

    for item in optimizer.optimizations:
        print(item)

    # 4. Generate optimized source
    print("\n[4] Generating optimized source...")
    optimized_source = CodeGenerator().generate(program)
    print(optimized_source)

    # 5. Parse the generated source again
    print("[5] Parsing generated source...")
    optimized_program = parse_source(optimized_source)
    print("PASS: Generated source parsed.")

    # 6. Re-run semantic analysis on generated source
    print("\n[6] Checking optimized source semantics...")
    optimized_analyzer = SemanticAnalyzer(optimized_program)
    if not optimized_analyzer.analyze():
        raise SystemExit(
            "FAIL: Optimized source failed semantic analysis."
        )

    print("PASS: Optimized source passed semantic analysis.")
    print("\nALL PIPELINE CHECKS PASSED.")


if __name__ == "__main__":
    main()
