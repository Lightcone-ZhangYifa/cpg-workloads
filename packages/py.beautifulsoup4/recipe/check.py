#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise HTML parsing, CSS selection, tree editing and invalid selectors."""
    soup = module.BeautifulSoup('<ul><li class="item">alpha &amp; beta</li><li class="item" data-n="2">second</li></ul>', "html.parser")
    items = soup.select("ul > li.item")
    require(len(items) == 2 and items[0].get_text() == "alpha & beta", "HTML/entity/CSS selection failed")
    require(items[1]["data-n"] == "2", "Attribute parsing failed")
    added = soup.new_tag("li", attrs={"class": "item"}); added.string = "third"; soup.ul.append(added)
    require(len(soup.select("li.item")) == 3, "Tree insertion failed")
    removed = items[0].extract()
    require(removed.parent is None and len(soup.select("li")) == 2, "Tree extraction failed")
    require(module.BeautifulSoup(str(soup), "html.parser").get_text() == "secondthird", "Serialization roundtrip failed")
    selector = installed_module("soupsieve")
    raises(selector.SelectorSyntaxError, lambda: soup.select("li["), "Invalid selector accepted")
    raises(module.FeatureNotFound, lambda: module.BeautifulSoup("<p>x</p>", "cpg-nonexistent-parser"), "Unknown parser accepted")
    return {"checks": ["html-entity-css", "attributes", "tree-insertion", "tree-extraction", "serialization", "invalid-css", "unknown-parser"], "parser": "stdlib html.parser"}

if __name__ == "__main__":
    raise SystemExit(main('beautifulsoup4', 'bs4', functional))
