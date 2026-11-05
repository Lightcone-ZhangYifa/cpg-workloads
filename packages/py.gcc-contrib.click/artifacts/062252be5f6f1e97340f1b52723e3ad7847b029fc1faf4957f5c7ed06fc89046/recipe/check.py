#!/usr/bin/env python3
"""Installed Click check with command invocations, errors and a real subprocess."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, require

def functional(click, work):
    """Check typed options, prompts, file arguments and exact CLI exit statuses."""
    testing = installed_module("click.testing")
    runner = testing.CliRunner()
    @click.command()
    @click.option("--count", type=click.IntRange(1, 4), default=2, envvar="CPG_CLICK_COUNT")
    @click.option("--upper", is_flag=True)
    @click.argument("name")
    def greet(count, upper, name):
        for _ in range(count): click.echo(name.upper() if upper else name)
    result = runner.invoke(greet, ["--count", "3", "--upper", "compiler"])
    require(result.exit_code == 0 and result.output == "COMPILER\n" * 3, "Typed options/flag result mismatch")
    env_result = runner.invoke(greet, ["compiler"], env={"CPG_CLICK_COUNT": "1"})
    require(env_result.exit_code == 0 and env_result.output == "compiler\n", "Environment option failed")
    for args in [["--count", "9", "name"], ["--unknown", "name"], []]:
        bad = runner.invoke(greet, args)
        require(bad.exit_code == 2 and "Error:" in bad.output, f"Invalid CLI was accepted: {args}")
    @click.command()
    @click.option("--name", prompt=True)
    def prompted(name): click.echo("hello " + name)
    prompt = runner.invoke(prompted, input="researcher\n")
    require(prompt.exit_code == 0 and "hello researcher" in prompt.output, "Prompt input failed")
    fixture = work / "input.txt"; fixture.write_text("alpha\nbeta\n")
    @click.command()
    @click.argument("source", type=click.File("r"))
    def read_file(source): click.echo(len(source.read().splitlines()))
    file_result = runner.invoke(read_file, [str(fixture)])
    require(file_result.exit_code == 0 and file_result.output == "2\n", "File argument failed")
    missing = runner.invoke(read_file, [str(work / "absent.txt")])
    require(missing.exit_code == 2, "Missing input file accepted")
    cli = work / "cli.py"
    cli.write_text("import click\n@click.command()\n@click.argument('number', type=int)\ndef cli(number): click.echo(number*number)\nif __name__ == '__main__': cli()\n")
    require(child([sys.executable, "-I", cli, "7"]).stdout == "49\n", "Real CLI subprocess failed")
    child([sys.executable, "-I", cli, "invalid"], expected=2)
    return {"checks": ["typed-options-and-flag", "environment-option", "invalid-range-option-and-missing-argument",
                       "interactive-prompt", "file-argument", "missing-file", "real-cli-success", "real-cli-error"]}

if __name__ == "__main__":
    raise SystemExit(main("click", "click", functional))
