#!/usr/bin/env python3
"""Compila CV/carta para o jobbot sem `cd` (no `claude -p`, `cd x && lualatex` pede aprovação).

Uso (a partir da raiz do candidato):
  python3 tools/jobbot_tex.py cv/main_empresa_cargo.tex
  python3 tools/jobbot_tex.py cover_letters/cover_empresa_cargo.tex
  python3 tools/jobbot_tex.py --clean cv/main_empresa_cargo.tex   # apaga .aux/.log/.out etc.

CV usa lualatex; carta usa xelatex (cover.cls procura fontes por caminho relativo à pasta).
"""

import re
import subprocess
import sys
from pathlib import Path

ENGINES = {"cv": "lualatex", "cover_letters": "xelatex"}
AUX = (".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk", ".synctex.gz", ".xdv")
NAME = re.compile(r"^[\w.-]+\.tex$")


def main(argv: list[str]) -> int:
    clean = "--clean" in argv
    args = [a for a in argv if a != "--clean"]
    if len(args) != 1:
        print(__doc__)
        return 2
    parts = Path(args[0]).parts
    if len(parts) != 2 or parts[0] not in ENGINES or not NAME.match(parts[1]):
        print("Caminho inválido: use cv/<nome>.tex ou cover_letters/<nome>.tex")
        return 2
    folder, name = Path(parts[0]).resolve(), parts[1]
    if not (folder / name).is_file():
        print(f"Arquivo não encontrado: {args[0]}")
        return 2
    if clean:
        stem = name[:-4]
        removed = [ext for ext in AUX if (folder / f"{stem}{ext}").is_file()]
        for ext in removed:
            (folder / f"{stem}{ext}").unlink()
        print(f"Removidos: {', '.join(stem + e for e in removed) or 'nada'}")
        return 0
    try:
        p = subprocess.run(
            [ENGINES[parts[0]], "-interaction=nonstopmode", "-halt-on-error", name],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("Tempo esgotado (300 s).")
        return 1
    print(p.stdout[-3000:])
    print(f"exit={p.returncode} pdf={'ok' if (folder / (name[:-4] + '.pdf')).exists() else 'ausente'}")
    return p.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
