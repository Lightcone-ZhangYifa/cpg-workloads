#!/usr/bin/env python3
"""Installed functional check for rich; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(rich, work):
    """Render to an in-memory console and check plain and ANSI output."""
    import io
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text
    table = Table("Resource", "Status")
    table.add_row("sqlite", "passed")
    buffer = io.StringIO()
    console = Console(file=buffer, width=60, color_system=None, record=True)
    console.print(table)
    text = console.export_text()
    require(all(word in text for word in ["Resource", "Status", "sqlite", "passed"]), "Rendered table lost content")
    require("\x1b[" not in buffer.getvalue(), "Plain console unexpectedly contains ANSI escapes")
    ansi = io.StringIO()
    Console(file=ansi, force_terminal=True, color_system="standard").print(Text("ready", style="bold green"))
    require("\x1b[" in ansi.getvalue() and "ready" in ansi.getvalue(), "Terminal styling did not render")
    return {"checks": ["table-rendering", "captured-plain-output", "ansi-styling"], "interactive_terminal": "not_required"}

if __name__ == "__main__":
    raise SystemExit(main('rich', 'rich', functional))
