import subprocess
import sys
from pathlib import Path

import main as main_module


COMPILER_DIR = Path(__file__).resolve().parents[1]


class MemoryOutput:
    def __init__(self):
        self.parent = self
        self.source = None

    def mkdir(self, **_kwargs):
        pass

    def write_text(self, source, encoding=None):
        self.source = source
        return len(source)

    def resolve(self):
        return "<memory-output.mc>"


def test_cli_help_lists_only_the_three_supported_domains():
    result = subprocess.run(
        [sys.executable, str(COMPILER_DIR / "main.py"), "--help"],
        cwd=COMPILER_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "{banking,supply_chain,voting}" in result.stdout
    assert "healthcare" not in result.stdout


def test_cli_rejects_removed_healthcare_domain():
    result = subprocess.run(
        [
            sys.executable,
            str(COMPILER_DIR / "main.py"),
            "--domain",
            "healthcare",
        ],
        cwd=COMPILER_DIR,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "invalid choice: 'healthcare'" in result.stderr


def test_cli_does_not_write_generated_source_that_fails_validation(
    monkeypatch,
):
    source = "contract Safe { function run() { return; } }"
    output = MemoryOutput()
    monkeypatch.setattr(
        main_module.CodeGenerator,
        "generate",
        lambda _self, _program: "not valid MiniChain",
    )
    monkeypatch.setattr(
        main_module, "choose_output_path", lambda *_args: output
    )

    result = main_module.run_pipeline(
        source,
        "banking",
        output_argument="memory-output.mc",
    )

    assert result == 1
    assert output.source is None
