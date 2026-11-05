#!/usr/bin/env python3
"""Installed functional check with deterministic local inputs."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import child, installed_module, main, raises, require

def functional(ms, work):
    """Check escaping, safe formatting, unescaping and decode/format errors."""
    require(ms.escape('a&<b>"\'') == 'a&amp;&lt;b&gt;&#34;&#39;', 'HTML character escaping mismatch')
    template = ms.Markup('<b>%s</b>')
    require(template % '<compiler>' == '<b>&lt;compiler&gt;</b>', 'Safe percent formatting failed')
    require(ms.Markup('<b>') + '<x>' == '<b>&lt;x&gt;', 'Safe concatenation failed')
    require(ms.Markup('<b>Hello &amp; compiler</b>').striptags() == 'Hello & compiler', 'Striptags/unescape failed')
    require(ms.Markup('&lt;x&gt;&amp;').unescape() == '<x>&', 'Entity unescape failed')
    require(ms.escape_silent(None) == '', 'Silent None handling mismatch')
    safe = ms.Markup('<i>safe</i>'); require(ms.soft_str(safe) is safe, 'Safe-string identity lost')
    raises(KeyError, lambda: ms.Markup('{missing}').format(), 'Missing format field accepted')
    raises(UnicodeDecodeError, lambda: ms.Markup(bytes([255]),'utf-8'), 'Invalid UTF-8 accepted')
    return {'checks':['html-escaping','safe-percent-format','safe-concatenation','striptags','unescape','none-handling','safe-string-identity','missing-format-field','invalid-encoding']}

if __name__ == "__main__":
    raise SystemExit(main('markupsafe', 'markupsafe', functional))
