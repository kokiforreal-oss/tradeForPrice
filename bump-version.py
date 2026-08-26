#!/usr/bin/env python3
"""每次升级时写入新构建号，并刷新静态资源 ?v=，避免浏览器继续用旧缓存。"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INDEX = ROOT / "app" / "static" / "index.html"
VERSION_FILE = ROOT / "VERSION"


def main() -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(r"\?v=[^\"'\s>]+", f"?v={stamp}", html)
    html = re.sub(r'(data-build=")[^"]*"', rf'\g<1>{stamp}"', html)
    INDEX.write_text(html, encoding="utf-8")
    VERSION_FILE.write_text(stamp + "\n", encoding="utf-8")
    print(stamp)
    return stamp


if __name__ == "__main__":
    main()
