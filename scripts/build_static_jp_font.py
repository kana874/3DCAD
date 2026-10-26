#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
"""Create a non-variable Japanese TTF from Google's OFL Noto Sans JP.

Run only in the Docker build, not in visitors' browsers.
"""
from pathlib import Path
import sys
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

def make_static(source: Path, target: Path) -> None:
    font = TTFont(source, lazy=False)
    assert "fvar" in font, "Expected a variable TTF source"
    assert any(axis.axisTag == "wght" for axis in font["fvar"].axes)
    font = instantiateVariableFont(font, {"wght": 400}, inplace=True)
    font.save(target, reorderTables=True)
    font.close()
    check = TTFont(target)
    assert not any(table in check for table in ("fvar", "gvar", "HVAR", "MVAR", "avar")), "Variable font tables still present"
    chars = check.getBestCmap()
    for ch in ("日", "本", "語", "設", "定", "編", "集", "表", "示"):
        assert ord(ch) in chars, f"Missing Japanese glyph: {ch}"
    check.close()
    print(f"Static NotoSansJP created: {target.stat().st_size} bytes")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: build_static_jp_font.py variable.ttf static.ttf")
    make_static(Path(sys.argv[1]), Path(sys.argv[2]))
