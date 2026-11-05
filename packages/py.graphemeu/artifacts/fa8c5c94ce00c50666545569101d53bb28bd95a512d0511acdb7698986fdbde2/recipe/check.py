#!/usr/bin/env python3
"""Exact installed distribution and bounded functional contract."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_support import installed_module, main, raises, require, child

def functional(module, work):
    """Count and slice composed characters, emoji and grapheme boundaries."""
    clusters = ["a\u0301", "🇨🇳", "👩\u200d🔬", "z"]
    text = "".join(clusters)
    require(list(module.graphemes(text)) == clusters and module.length(text) == 4, "Grapheme segmentation failed")
    require(module.slice(text, 1, 3) == "".join(clusters[1:3]), "Grapheme slice split a cluster")
    require(module.contains(text, clusters[0]) and not module.contains(text, "\u0301"), "Cluster-aware contains failed")
    require(module.length("") == 0 and list(module.graphemes("")) == [], "Empty input failed")
    require(module.length("compiler") == 8, "ASCII length failed")
    raises(TypeError, lambda: module.length(None), "Invalid text input accepted")
    return {"checks": ["combining-marks", "regional-indicator-flag", "zwj-emoji", "cluster-slice", "cluster-contained-negative", "empty-input", "ascii", "invalid-type"]}

if __name__ == "__main__":
    raise SystemExit(main('graphemeu', 'grapheme', functional))
