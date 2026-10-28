import argparse
import sys
from pathlib import Path

from lexer import Lexer
from parser import Parser, ParserError
from semantic import SemanticAnalyzer
from domain_analyzer import DomainAnalyzer
from optimizer import Optimizer
from codegen import CodeGenerator, CodeGenerationError


DEMO_SOURCE = """
contract Bank {
    state balance : int;
    state owner : address;

    function deposit(amount : int) {
        require(amount > 0);
        int doubled = amount * 2;
        int quadrupled = amount * 4;
        int octupled = amount * 8;
        balance = balance + amount + 0;
    }

    function withdraw(amount : int) {
        require(amount > 0);
        require(amount <= balance);
        balance = balance - amount;
    }

    function getBalance() : int {
        return balance + 0;
    }
}
"""


def read_source(source_path):
    if source_path is None:
        print("No source file supplied; running the built-in MiniChain demo.")
        return DEMO_SOURCE

    path = Path(source_path)

    if not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")

    return path.read_text(encoding="utf-8")


def choose_output_path(source_path, contract_name, output_argument):
    if output_argument:
        return Path(output_argument)

    if source_path:
        source = Path(source_path)
        return source.with_name(f"{source.stem}_optimized.mc")

    return Path(f"{contract_name}_optimized.mc")


def print_optimization_report(optimizer):
    if optimizer.optimizations:
        print(f"Optimizations applied: {len(optimizer.optimizations)}")
        for optimization in optimizer.optimizations:
            print(f"  {optimization}")
    else:
        print("No optimizations were applied.")

    if optimizer.warnings:
        print("Warnings:")
        for warning in optimizer.warnings:
            print(f"  WARNING: {warning}")
    else:
        print("No unused-variable warnings.")


def run_pipeline(source, domain, source_path=None, output_argument=None):
    print("\n" + "=" * 60)
    print("MINICHAIN COMPILER")
    print("=" * 60)

    # 1. Lexical analysis
    print("\n[1/5] LEXICAL ANALYSIS")
    try:
        tokens = Lexer(source).tokenize()
    except SyntaxError as error:
        print(f"Lexical analysis failed: {error}")
        return 1

    print(f"Lexical analysis successful. Tokens generated: {len(tokens) - 1}")

    # 2. Syntax analysis
    print("\n[2/5] SYNTAX ANALYSIS")
    try:
        program = Parser(tokens).parse()
    except ParserError as error:
        print(f"Syntax analysis failed: {error}")
        return 1

    print("Syntax analysis successful. AST created.")

    # 3. Semantic analysis
    print("\n[3/5] SEMANTIC ANALYSIS")
    semantic_analyzer = SemanticAnalyzer(program)
    if not semantic_analyzer.analyze():
        print("MiniChain stopped because semantic errors were found.")
        return 1

    # 4. Domain analysis
    print("\n[4/5] DOMAIN ANALYSIS")
    try:
        domain_analyzer = DomainAnalyzer(program, domain)
        domain_analyzer.analyze()
        domain_analyzer.print_report()
    except ValueError as error:
        print(f"Domain analysis failed: {error}")
        return 1

    # 5. Optimize and generate optimized source
    print("\n[5/5] OPTIMIZATION")
    optimizer = Optimizer(program)
    optimizer.optimize()
    print_optimization_report(optimizer)

    try:
        optimized_source = CodeGenerator().generate(program)

        # Validate exactly the text that will be written to disk.
        try:
            optimized_program = Parser(
                Lexer(optimized_source).tokenize()
            ).parse()
        except (SyntaxError, ParserError) as error:
            raise CodeGenerationError(
                f"Generated source failed parsing: {error}"
            ) from error

        optimized_semantic_analyzer = SemanticAnalyzer(optimized_program)
        if not optimized_semantic_analyzer.analyze():
            details = "; ".join(optimized_semantic_analyzer.errors)
            raise CodeGenerationError(
                "Generated source failed semantic validation"
                + (f": {details}" if details else ".")
            )

        output_path = choose_output_path(
            source_path,
            program.contract.name,
            output_argument
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(optimized_source, encoding="utf-8")
    except (OSError, CodeGenerationError) as error:
        print(f"\nCould not generate optimized source: {error}")
        return 1

    print("\n" + "=" * 60)
    print("MINICHAIN ANALYSIS COMPLETED")
    print("=" * 60)
    print(f"Optimized source saved to: {output_path.resolve()}")
    print("The generated file contains the optimized AST converted back to MiniChain source.")
    return 0


def main():
    argument_parser = argparse.ArgumentParser(
        description="Run the MiniChain smart-contract compiler pipeline."
    )
    argument_parser.add_argument(
        "source",
        nargs="?",
        help="Path to a MiniChain source file. If omitted, the built-in demo runs."
    )
    argument_parser.add_argument(
        "--domain",
        choices=["banking", "supply_chain", "voting"],
        default="banking",
        help="Application domain (default: banking)."
    )
    argument_parser.add_argument(
        "--output",
        help="Path for the generated optimized .mc source file."
    )

    args = argument_parser.parse_args()

    try:
        source = read_source(args.source)
    except (OSError, UnicodeError) as error:
        print(f"Could not read source file: {error}")
        return 1

    return run_pipeline(
        source,
        args.domain,
        source_path=args.source,
        output_argument=args.output
    )


if __name__ == "__main__":
    sys.exit(main())
