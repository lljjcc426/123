"""Compile the hand-written LaTeX paper with XeLaTeX."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


PAPER_DIR = Path(__file__).resolve().parent
SOURCE = PAPER_DIR / "main.tex"
FINAL_PDF = PAPER_DIR / "超声预约优化论文.pdf"
BUILD_SUFFIXES = (".aux", ".log", ".out", ".pdf")
XELATEX_FALLBACK = (
    Path.home() / "AppData/Local/Programs/MiKTeX/miktex/bin/x64/xelatex.exe"
)


def find_xelatex() -> str:
    located = shutil.which("xelatex")
    if located:
        return located
    if XELATEX_FALLBACK.exists():
        return str(XELATEX_FALLBACK)
    raise FileNotFoundError("未找到 XeLaTeX，请先安装 MiKTeX 或 TeX Live")


def main() -> None:
    command = [
        find_xelatex(),
        "-interaction=nonstopmode",
        "-file-line-error",
        "-halt-on-error",
        SOURCE.name,
    ]
    for _ in range(2):
        subprocess.run(command, cwd=PAPER_DIR, check=True)
    shutil.copy2(SOURCE.with_suffix(".pdf"), FINAL_PDF)
    for suffix in BUILD_SUFFIXES:
        SOURCE.with_suffix(suffix).unlink(missing_ok=True)
    print(SOURCE)
    print(FINAL_PDF)


if __name__ == "__main__":
    main()
