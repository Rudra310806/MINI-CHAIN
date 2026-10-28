
from lexer import Lexer
from parser import Parser
from domain_analyzer import DomainAnalyzer


NEGATIVE_CASES = {
    "banking": {
        "source": """
contract UnsafeBank {
    state balance : int;

    function deposit(amount : int) {
        balance = balance + amount;
    }

    function withdraw(amount : int) {
        balance = balance - amount;
    }

    function transfer(amount : int) {
        balance = balance - amount;
    }
}
""",
        "expected_rule_ids": {
            "BANK-001",
            "BANK-002",
            "BANK-004",
            "BANK-006",
            "BANK-007",
        },
    },

    "supply_chain": {
        "source": """
contract UnsafeSupplyChain {
    state status : string;
    state owner : address;

    function registerProduct() {
        status = "registered";
    }

    function dispatchProduct() {
        status = "dispatched";
    }

    function deliverProduct() {
        status = "delivered";
    }

    function transferOwnership(new_owner : address) {
        owner = new_owner;
    }
}
""",
        "expected_rule_ids": {
            "SC-002",
            "SC-003",
            "SC-004",
        },
    },

    "voting": {
        "source": """
contract UnsafeGovernance {
    state voting_open : bool;
    state eligible : bool;
    state has_voted : bool;
    state vote_count : int;

    function vote() {
        vote_count = vote_count + 1;
    }
}
""",
        "expected_rule_ids": {
            "VOTE-001",
            "VOTE-002",
            "VOTE-003",
        },
    },
}


def parse_source(source):
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def main():
    all_passed = True

    for domain, case in NEGATIVE_CASES.items():
        print("\n" + "=" * 64)
        print(f"NEGATIVE DOMAIN TEST: {domain.upper()}")
        print("=" * 64)

        program = parse_source(case["source"])
        print("PASS: Unsafe example parsed.")

        analyzer = DomainAnalyzer(program, domain)
        issues = analyzer.analyze()
        analyzer.print_report()

        found_rule_ids = {issue.rule_id for issue in issues}
        expected_rule_ids = case["expected_rule_ids"]
        missing = expected_rule_ids - found_rule_ids

        if missing:
            all_passed = False
            print(
                f"FAIL: Expected rule IDs not reported: "
                f"{sorted(missing)}"
            )
        else:
            print("PASS: All expected warning rule IDs were detected.")

        print(f"Expected rule IDs: {sorted(expected_rule_ids)}")
        print(f"Detected rule IDs: {sorted(found_rule_ids)}")

    print("\n" + "=" * 64)

    if all_passed:
        print("ALL NEGATIVE DOMAIN TESTS PASSED.")
    else:
        print("SOME NEGATIVE DOMAIN TESTS FAILED.")
        raise SystemExit(1)

    print(
        "Note: These tests check heuristic rules against deliberately "
        "unsafe examples; passing does not prove contract security."
    )


if __name__ == "__main__":
    main()
