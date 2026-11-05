#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Parse safe XML and reject entity expansion and prohibited DTD input."""
    xml = installed_module("defusedxml.ElementTree")
    common = installed_module("defusedxml.common")
    tree = xml.fromstring('<root><item value="3">alpha &amp; beta</item></root>')
    require(tree.tag == "root" and tree.find("item").text == "alpha & beta", "Safe XML parsing failed")
    require(tree.find("item").get("value") == "3", "XML attributes failed")
    fixture = work / "safe.xml"; fixture.write_text('<root><item>local</item></root>')
    require(xml.parse(fixture).getroot().find("item").text == "local", "File XML parsing failed")
    entity = '<!DOCTYPE root [<!ENTITY x "expanded">]><root>&x;</root>'
    raises(common.EntitiesForbidden, lambda: xml.fromstring(entity), "Entity declaration accepted")
    raises(common.DTDForbidden, lambda: xml.fromstring('<!DOCTYPE root><root/>', forbid_dtd=True), "Prohibited DTD accepted")
    raises(xml.ParseError, lambda: xml.fromstring("<root>"), "Malformed XML accepted")
    return {"checks": ["safe-xml", "attributes", "file-parsing", "entity-rejection", "dtd-rejection", "malformed-input"]}

if __name__ == "__main__":
    raise SystemExit(main('defusedxml', 'defusedxml', functional))
