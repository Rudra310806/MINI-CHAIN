
from pathlib import Path

from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer
from optimizer import Optimizer
from codegen import CodeGenerator
from domain_analyzer import DomainAnalyzer


CASES = {
    "banking": """
contract Bank {
    state balance : int;

    function deposit(amount : int) : int {
        int adjusted = amount + 0;
        int doubled = amount * 2;
        int fee = 3 * 4;
        require(amount > 0);
        balance = balance + amount;
        return doubled + fee;
    }

    function withdraw(amount : int) {
        require(amount > 0);
        require(amount <= balance);
        balance = balance - amount;
    }
}
""",
    "supply_chain": """
contract SupplyChain {
    state status : string;
    state owner : address;

    function registerProduct() {
        status = "registered";
    }

    function dispatchProduct() {
        int dispatchCode = 2 * 4;
        require(status == "registered");
        status = "dispatched";
    }

    function deliverProduct() {
        int deliveryCode = 10 + 0;
        require(status == "dispatched");
        status = "delivered";
    }

    function transferOwnership(new_owner : address) {
        require(owner == new_owner);
        owner = new_owner;
    }
}
""",
    "voting": """
contract Governance {
    state voting_open : bool;
    state eligible : bool;
    state has_voted : bool;
    state vote_count : int;

    function vote() {
        int voteWeight = 1 * 2;
        require(voting_open == true);
        require(eligible == true);
        require(has_voted == false);
        has_voted = true;
        vote_count = vote_count + 1 + 0;
    }
}
""",
}


def parse_source(source):
    return Parser(Lexer(source).tokenize()).parse()


def run_case(domain, source, output_dir):
    print("\n" + "=" * 60)
    print(f"DOMAIN: {domain.upper()}")
    print("=" * 60)

    program = parse_source(source)
    print("PASS: Original source parsed.")

    original_program = parse_source(source)
    original_analyzer = SemanticAnalyzer(original_program)

    if not original_analyzer.analyze():
        raise RuntimeError(
            f"{domain}: original semantic analysis failed"
        )

    print("PASS: Original semantic analysis.")

    domain_analyzer = DomainAnalyzer(program, domain)
    issues = domain_analyzer.analyze()
    domain_analyzer.print_report()

    optimizer = Optimizer(program)
    optimizer.optimize()

    optimized_source = CodeGenerator().generate(program)

    print("\nOPTIMIZATIONS APPLIED:")
    for item in optimizer.optimizations:
        print(item)

    print("\nOPTIMIZED SOURCE:")
    print(optimized_source)

    # Save optimized source to a separate file.
    output_path = output_dir / f"{domain}_optimized.mc"
    output_path.write_text(optimized_source, encoding="utf-8")

    print(f"SAVED FILE: {output_path.resolve()}")

    # Read the saved file and validate that exact file.
    saved_source = output_path.read_text(encoding="utf-8")
    saved_program = parse_source(saved_source)
    print("PASS: Saved optimized source parsed.")

    saved_semantic = SemanticAnalyzer(saved_program)

    if not saved_semantic.analyze():
        raise RuntimeError(
            f"{domain}: saved optimized source failed semantic analysis"
        )

    print("PASS: Saved optimized source passed semantic analysis.")
    print(f"Domain findings: {len(issues)}")
    print(f"Optimizer transformations: {len(optimizer.optimizations)}")
    print(f"Optimizer warnings: {len(optimizer.warnings)}")

    if optimizer.warnings:
        print("WARNING DETAILS:")
        for warning in optimizer.warnings:
            print(warning)

    if not optimizer.optimizations:
        raise RuntimeError(
            f"{domain}: no optimization transformations were applied"
        )

    return output_path


def main():
    output_dir = Path("optimized_outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_files = []

    for domain, source in CASES.items():
        output_files.append(
            run_case(domain, source, output_dir)
        )

    print("\n" + "=" * 60)
    print("ALL THREE DOMAIN PIPELINES PASSED.")
    print("OPTIMIZED FILES:")

    for path in output_files:
        print(path.resolve())

    print("\nThese are test outputs, not security-certified contracts.")


if __name__ == "__main__":
    main()
