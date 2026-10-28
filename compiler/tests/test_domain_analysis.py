import contextlib
import io
from pathlib import Path

import pytest

from domain_analyzer import DomainAnalyzer
from lexer import Lexer
from parser import Parser
from semantic import SemanticAnalyzer
from repair import repair_source

# Reuse the source examples from the existing script-based checks.
from test_domain_negative import NEGATIVE_CASES
from test_domain_pipeline import CASES as PIPELINE_POSITIVE_CASES
from test_domain_pipeline_save import CASES as SAVE_POSITIVE_CASES


def parse_source(source):
    return Parser(Lexer(source).tokenize()).parse()


def semantic_result(program):
    analyzer = SemanticAnalyzer(program)
    with contextlib.redirect_stdout(io.StringIO()):
        result = analyzer.analyze()
    return result, analyzer.errors


def banking_rule_ids(source):
    program = parse_source(source)
    issues = DomainAnalyzer(program, "banking").analyze()
    return {issue.rule_id for issue in issues}


def analyze_domain(source, domain):
    program = parse_source(source)
    return DomainAnalyzer(program, domain).analyze()


def test_bank_003_accepts_lowercase_amount_withdrawal():
    source = """
    contract Bank {
        state balance : int;
        function withdraw(amount : int) {
            require(amount > 0);
            require(amount <= balance);
            balance = balance - amount;
        }
    }
    """

    assert banking_rule_ids(source) == set()


def test_bank_003_accepts_mixed_case_amount_parameter():
    source = """
    contract Bank {
        state balance : int;
        function withdraw(Amount : int) {
            require(Amount > 0);
            require(Amount <= balance);
            balance = balance - Amount;
        }
    }
    """

    assert "BANK-003" not in banking_rule_ids(source)


def test_bank_003_still_reports_withdrawal_without_amount_subtraction():
    source = """
    contract Bank {
        state balance : int;
        function withdraw(amount : int) {
            require(amount > 0);
            require(amount <= balance);
            balance = balance + amount;
        }
    }
    """

    assert "BANK-003" in banking_rule_ids(source)


def test_banking_guards_use_mixed_case_amount_parameter_spelling():
    source = """
    contract Bank {
        state balance : int;
        function withdraw(Amount : int) {
            require(Amount > 0);
            require(Amount <= balance);
            balance = balance - Amount;
        }
    }
    """

    assert banking_rule_ids(source) == set()


def test_bank_009_accepts_guards_before_balance_mutation():
    source = """
    contract Bank {
        state balance : int;
        function withdraw(amount : int) {
            require(amount > 0);
            require(amount <= balance);
            balance = balance - amount;
        }
    }
    """

    assert "BANK-009" not in banking_rule_ids(source)


def test_bank_009_reports_guards_that_follow_balance_mutation():
    source = """
    contract Bank {
        state balance : int;
        function withdraw(amount : int) {
            balance = balance - amount;
            require(amount > 0);
            require(amount <= balance);
        }
    }
    """

    issues = analyze_domain(source, "banking")
    assert {issue.rule_id for issue in issues} == {"BANK-009"}
    assert all(issue.severity == "WARNING" for issue in issues)


def test_bank_010_reports_guard_after_balance_write_inside_nested_block():
    source = """
    contract Bank {
        state balance : int;
        function withdraw(amount : int, enabled : bool) {
            require(amount <= balance);
            if (enabled) {
                balance = balance - amount;
                require(amount > 0);
            }
        }
    }
    """

    issues = analyze_domain(source, "banking")
    assert {issue.rule_id for issue in issues} == {"BANK-010"}
    assert all(issue.severity == "WARNING" for issue in issues)


@pytest.mark.parametrize(
    "source",
    [
        """
        contract Bank {
            state balance : int;
            function withdraw(amount : int, enabled : bool) {
                require(amount <= balance);
                if (enabled) {
                    require(amount > 0);
                    balance = balance - amount;
                }
            }
        }
        """,
        """
        contract Bank {
            state balance : int;
            function withdraw(amount : int, enabled : bool) {
                require(amount <= balance);
                if (amount > 0 && enabled) {
                    balance = balance - amount;
                }
            }
        }
        """,
        """
        contract Bank {
            state balance : int;
            function withdraw(amount : int, enabled : bool) {
                require(amount <= balance);
                require(amount > 0 || enabled);
                if (enabled) {
                    balance = balance - amount;
                    require(amount > 0);
                }
            }
        }
        """,
    ],
    ids=[
        "guard-first-in-nested-block",
        "guard-in-controlling-condition",
        "disjunction-does-not-guarantee-guard",
    ],
)
def test_bank_010_reports_only_when_no_guaranteed_guard_precedes_write(source):
    # The disjunction does not guarantee amount > 0, so its later matching
    # require remains correctly reported as late.
    has_disjunction = "||" in source
    assert ("BANK-010" in banking_rule_ids(source)) is has_disjunction


POSITIVE_CASES = {
    **{f"pipeline:{domain}": (domain, source)
       for domain, source in PIPELINE_POSITIVE_CASES.items()},
    **{f"save_pipeline:{domain}": (domain, source)
       for domain, source in SAVE_POSITIVE_CASES.items()},
}


@pytest.mark.parametrize(
    ("case_name", "case"),
    sorted(POSITIVE_CASES.items()),
    ids=sorted(POSITIVE_CASES),
)
def test_existing_valid_domain_examples_have_no_findings(case_name, case):
    domain, source = case
    program = parse_source(source)
    valid, errors = semantic_result(program)

    assert valid, f"{case_name} semantic errors: {errors}"

    # The legacy Supply Chain transfer example's owner == new_owner guard is
    # accepted by the current heuristic; this test records its output only.
    issues = DomainAnalyzer(program, domain).analyze()
    assert issues == [], [str(issue) for issue in issues]


@pytest.mark.parametrize(
    ("domain", "case"),
    sorted(NEGATIVE_CASES.items()),
    ids=sorted(NEGATIVE_CASES),
)
def test_existing_unsafe_domain_examples_report_expected_rule_ids(domain, case):
    program = parse_source(case["source"])
    issues = DomainAnalyzer(program, domain).analyze()
    found_rule_ids = {issue.rule_id for issue in issues}

    assert found_rule_ids == case["expected_rule_ids"]
    assert all(issue.severity == "WARNING" for issue in issues)


def test_supply_chain_transition_rules_accept_complete_state_changes():
    source = """
    contract SupplyChain {
        state status : string;
        state owner : address;

        function registerProduct() {
            status = "registered";
        }

        function dispatchProduct() {
            require(status == "registered");
            status = "dispatched";
        }

        function deliverProduct() {
            require(status == "dispatched");
            status = "delivered";
        }

        function transferOwnership(new_owner : address) {
            require(owner == new_owner);
            owner = new_owner;
        }
    }
    """

    assert analyze_domain(source, "supply_chain") == []


@pytest.mark.parametrize(
    ("source", "expected_rule"),
    [
        (
            '''contract SupplyChain {
                state status : string;
                function registerProduct() { status = "pending"; }
            }''',
            "SC-008",
        ),
        (
            '''contract SupplyChain {
                state status : string;
                function dispatchProduct() {
                    require(status == "registered");
                    status = "registered";
                }
            }''',
            "SC-005",
        ),
        (
            '''contract SupplyChain {
                state status : string;
                function deliverProduct() {
                    require(status == "dispatched");
                    status = "dispatched";
                }
            }''',
            "SC-006",
        ),
        (
            '''contract SupplyChain {
                state owner : address;
                function transferOwnership(new_owner : address) {
                    require(owner == new_owner);
                    owner = owner;
                }
            }''',
            "SC-007",
        ),
    ],
    ids=["registration-status", "dispatch-status", "delivery-status", "owner-update"],
)
def test_supply_chain_transition_rules_report_missing_updates(source, expected_rule):
    issues = analyze_domain(source, "supply_chain")
    assert {issue.rule_id for issue in issues} == {expected_rule}
    assert all(issue.severity == "WARNING" for issue in issues)


@pytest.mark.parametrize(
    ("function_name", "source"),
    [
        (
            "dispatchProduct",
            '''contract SupplyChain {
                state status : string;
                function dispatchProduct() {
                    status = "dispatched";
                    require(status == "registered");
                }
            }''',
        ),
        (
            "deliverProduct",
            '''contract SupplyChain {
                state status : string;
                function deliverProduct() {
                    status = "delivered";
                    require(status == "dispatched");
                }
            }''',
        ),
    ],
    ids=["dispatch", "delivery"],
)
def test_sc_009_reports_top_level_status_write_before_prior_state_guard(
    function_name, source
):
    issues = analyze_domain(source, "supply_chain")
    assert {issue.rule_id for issue in issues} == {"SC-009"}
    assert issues[0].function == function_name
    assert issues[0].severity == "WARNING"


def test_sc_009_recognizes_exact_supply_chain_browser_fixture():
    fixture = Path(__file__).parent / "fixtures" / "supply_chain_review_demo.mc"
    source = fixture.read_text(encoding="utf-8")

    issues = analyze_domain(source, "supply_chain")

    assert {
        issue.rule_id
        for issue in issues
        if issue.function == "dispatchShipment"
    } == {"SC-009"}


@pytest.mark.parametrize(
    "source",
    [
        '''contract SupplyChain {
            state status : string;
            function dispatchProduct() {
                require(status == "registered");
                status = "dispatched";
            }
        }''',
        '''contract SupplyChain {
            state status : string;
            function deliverProduct() {
                require(status == "shipped");
                status = "delivered";
            }
        }''',
        '''contract SupplyChain {
            state status : string;
            state bypass : bool;
            function dispatchProduct() {
                require(status == "registered" || bypass);
                status = "dispatched";
                require(status == "registered");
            }
        }''',
    ],
    ids=[
        "dispatch-guard-first",
        "delivery-alternate-recognized-prior-state",
        "disjunction-does-not-guarantee-status",
    ],
)
def test_sc_009_checks_only_guaranteed_prior_state_guards(source):
    found = {issue.rule_id for issue in analyze_domain(source, "supply_chain")}
    assert ("SC-009" in found) is ("||" in source)


def test_vote_005_accepts_not_voted_guard_before_marking_the_same_flag():
    source = """
    contract Governance {
        state voting_open : bool;
        state eligible : bool;
        state Has_Voted : bool;
        state vote_count : int;

        function vote() {
            require(voting_open == true);
            require(eligible == true);
            require(!Has_Voted);
            Has_Voted = true;
            vote_count = vote_count + 1;
        }
    }
    """

    assert analyze_domain(source, "voting") == []


def test_vote_005_reports_duplicate_flag_marked_before_its_guard():
    source = """
    contract Governance {
        state voting_open : bool;
        state eligible : bool;
        state has_voted : bool;
        state vote_count : int;

        function vote() {
            require(voting_open == true);
            require(eligible == true);
            has_voted = true;
            vote_count = vote_count + 1;
            require(has_voted == false);
        }
    }
    """

    issues = analyze_domain(source, "voting")
    assert {issue.rule_id for issue in issues} == {"VOTE-005"}
    assert all(issue.severity == "WARNING" for issue in issues)


def test_vote_006_reports_direct_false_eligibility_require():
    source = """
    contract Governance {
        state voting_open : bool;
        state eligible : bool;
        state has_voted : bool;
        state vote_count : int;
        function vote() {
            require(voting_open == true);
            require(eligible == false);
            require(!has_voted);
            has_voted = true;
            vote_count = vote_count + 1;
        }
    }
    """

    issues = analyze_domain(source, "voting")
    assert {issue.rule_id for issue in issues} == {"VOTE-006"}
    assert issues[0].severity == "WARNING"


def test_vote_007_reports_direct_false_voting_period_require():
    source = """
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
    """

    issues = analyze_domain(source, "voting")
    assert {issue.rule_id for issue in issues} == {"VOTE-007"}
    assert issues[0].severity == "WARNING"


def test_vote_006_and_007_accept_positive_boolean_guards():
    source = """
    contract Governance {
        state voting_open : bool;
        state eligible : bool;
        state has_voted : bool;
        state vote_count : int;
        function vote() {
            require(voting_open);
            require(eligible == true);
            require(!has_voted);
            has_voted = true;
            vote_count = vote_count + 1;
        }
    }
    """

    assert not ({issue.rule_id for issue in analyze_domain(source, "voting")}
                & {"VOTE-006", "VOTE-007"})


def test_vote_006_and_007_ignore_unrecognized_or_nested_false_guards():
    source = """
    contract Governance {
        state voting_open : bool;
        state eligible : bool;
        state has_voted : bool;
        state paused : bool;
        state vote_count : int;
        function vote() {
            require(voting_open);
            require(eligible);
            require(!has_voted);
            if (paused) { require(!eligible); }
            has_voted = true;
            vote_count = vote_count + 1;
        }
    }
    """

    found = {issue.rule_id for issue in analyze_domain(source, "voting")}
    assert not (found & {"VOTE-006", "VOTE-007"})


@pytest.mark.parametrize(
    ("domain", "rule_id"),
    [
        ("voting", "VOTE-006"),
        ("voting", "VOTE-007"),
    ],
)
def test_new_domain_rules_are_explicitly_skipped_by_automatic_repair(
    domain, rule_id
):
    original = "contract Minimal { function run() { return; } }"
    repaired, applied, skipped = repair_source(
        original,
        domain,
        [{"rule_id": rule_id, "function": "run"}],
    )

    assert repaired == original
    assert applied == []
    assert [item["rule_id"] for item in skipped] == [rule_id]
    assert "Automatic repair is unsupported" in skipped[0]["reason"]
    assert "explicit policy" in skipped[0]["reason"]


def test_healthcare_is_not_a_supported_analysis_domain():
    program = parse_source("contract Example { function run() { return; } }")

    with pytest.raises(ValueError, match="Unknown domain: healthcare"):
        DomainAnalyzer(program, "healthcare")
