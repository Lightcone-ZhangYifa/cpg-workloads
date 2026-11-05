#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Exercise finite cycles, pairwise addition, products and invalid composition."""
    colors = module.cycler(color=["red", "blue"])
    styles = module.cycler(style=["solid", "dash"])
    paired = colors + styles
    require(list(paired) == [{"color": "red", "style": "solid"}, {"color": "blue", "style": "dash"}], "Paired composition failed")
    product = colors * styles
    require(len(product) == 4 and list(product)[-1] == {"color": "blue", "style": "dash"}, "Cartesian product failed")
    require(colors.by_key() == {"color": ["red", "blue"]}, "by_key failed")
    require(list(colors * 2) == list(colors) * 2, "Cycle repetition failed")
    raises(ValueError, lambda: colors + module.cycler(style=["one"]), "Unequal cycle sizes accepted")
    raises(ValueError, lambda: colors + colors, "Duplicate keys accepted")
    require(list(colors) == [{"color": "red"}, {"color": "blue"}], "Composition mutated inputs")
    return {"checks": ["paired-composition", "cartesian-product", "by-key", "repetition", "unequal-sizes", "duplicate-keys", "input-preservation"]}

if __name__ == "__main__":
    raise SystemExit(main('cycler', 'cycler', functional))
