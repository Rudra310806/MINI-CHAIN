
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


def run_case(domain, source):
    print("\n" + "=" * 64)
    print(f"DOMAIN: {domain.upper()}")
    print("=" * 64)

    # Parse original source.
    program = parse_source(source)
    print("PASS: Original source parsed.")

    # Validate original source.
    original_program = parse_source(source)
    original_analyzer = SemanticAnalyzer(original_program)

    if not original_analyzer.analyze():
        raise RuntimeError(
            f"{domain}: original semantic analysis failed"
        )

    print("PASS: Original semantic analysis.")

    # Run domain-specific checks on the original source.
    domain_analyzer = DomainAnalyzer(program, domain)
    issues = domain_analyzer.analyze()
    domain_analyzer.print_report()

    # Optimize the AST.
    optimizer = Optimizer(program)
    optimizer.optimize()

    # Generate optimized source.
    optimized_source = CodeGenerator().generate(program)

    print("\nOPTIMIZATIONS APPLIED:")
    if optimizer.optimizations:
        for item in optimizer.optimizations:
            print(item)
    else:
        print("No transformations applied.")

    print("\nOPTIMIZED SOURCE:")
    print(optimized_source)

    # Re-parse optimized source.
    optimized_program = parse_source(optimized_source)
    print("PASS: Optimized source parsed.")

    # Re-check optimized semantics.
    optimized_analyzer = SemanticAnalyzer(optimized_program)

    if not optimized_analyzer.analyze():
        raise RuntimeError(
            f"{domain}: optimized semantic analysis failed"
        )

    print("PASS: Optimized semantic analysis.")

    # Summary.
    print(f"\nDomain findings: {len(issues)}")
    print(
        f"Optimizer transformations: "
        f"{len(optimizer.optimizations)}"
    )
    print(f"Optimizer warnings: {len(optimizer.warnings)}")

    if optimizer.warnings:
        print("\nWARNING DETAILS:")
        for warning in optimizer.warnings:
            print(warning)

    # Fail this test if none of the expected optimizations ran.
    if not optimizer.optimizations:
        raise RuntimeError(
            f"{domain}: expected at least one optimization, "
            "but none were applied."
        )


def main():
    for domain, source in CASES.items():
        run_case(domain, source)

    print("\nALL THREE DOMAIN PIPELINE TESTS PASSED.")


if __name__ == "__main__":
    main()
