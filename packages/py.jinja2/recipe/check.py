#!/usr/bin/env python3
"""Installed functional check for jinja2; no network access required."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(jinja, work):
    """Render controlled templates, apply autoescaping and reject missing inputs."""
    environment = jinja.Environment(loader=jinja.DictLoader({"report.html": "<b>{{ label }}</b>{% for x in values %} {{ x }}{% endfor %}"}), autoescape=jinja.select_autoescape(["html"]), undefined=jinja.StrictUndefined)
    rendered = environment.get_template("report.html").render(label="<compiler>", values=[1, 2])
    require(rendered == "<b>&lt;compiler&gt;</b> 1 2", "Template output/escaping mismatch")
    raises(jinja.UndefinedError, lambda: environment.get_template("report.html").render(values=[]), "Undefined variable was accepted")
    raises(jinja.TemplateNotFound, lambda: environment.get_template("missing.html"), "Missing template was accepted")
    raises(jinja.TemplateSyntaxError, lambda: environment.from_string("{% if %}"), "Invalid syntax was accepted")
    return {"checks": ["loop-render", "html-escaping", "strict-undefined", "missing-template", "syntax-error"]}

if __name__ == "__main__":
    raise SystemExit(main('jinja2', 'jinja2', functional))
