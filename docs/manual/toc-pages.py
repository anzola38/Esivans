"""Dice en que pagina del PDF cae cada destino de los enlaces internos (tabla de contenido e indice de figuras).

    uv run --with pymupdf python docs/manual/toc-pages.py <archivo.pdf>

Imprime JSON: {"pages": N, "targets": {"id-del-destino": pagina, ...}}. Lo usa build.mjs.
"""
import json
import sys
from urllib.parse import unquote

import pymupdf as fitz

doc = fitz.open(sys.argv[1])
targets = {}
for page in doc:
    for link in page.get_links():
        name = link.get("nameddest") or link.get("name")
        number = link.get("page")
        if name and isinstance(number, int) and number >= 0:
            targets[unquote(name)] = number + 1
print(json.dumps({"pages": doc.page_count, "targets": targets}))
