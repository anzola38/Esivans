"""Mide el espacio en blanco al final de cada pagina del PDF y dice que bloque quedo arriba de la siguiente.

    uv run --with pymupdf python docs/manual/page-gaps.py <archivo.pdf>

Imprime JSON: {"pages": [{"page": n, "free_mm": x, "last": bool}], "tops": {"id-de-figura": {"page": n, "y_mm": y, "h_mm": h}}}
Lo usa build.mjs para encoger las figuras que saltaron de pagina por poco (ver fitFigures).
"""
import json
import sys
from urllib.parse import unquote

import pymupdf

MM = 72 / 25.4
TOP = 21 * MM       # margen superior de @page
BOTTOM = 20 * MM    # margen inferior de @page

doc = pymupdf.open(sys.argv[1])
height = doc[0].rect.height
pages = []
for page in doc:
    lowest = TOP
    for block in page.get_text("blocks"):
        y1 = block[3]
        if y1 < height - BOTTOM + 2:
            lowest = max(lowest, y1)
    for info in page.get_image_info():
        y1 = info["bbox"][3]
        if y1 < height - BOTTOM + 2:
            lowest = max(lowest, y1)
    for drawing in page.get_drawings():
        rect = drawing["rect"]
        if rect.y1 < height - BOTTOM + 2 and rect.height < height * 0.9:
            lowest = max(lowest, rect.y1)
    pages.append({"page": page.number + 1, "free_mm": round((height - BOTTOM - lowest) / MM, 1)})

# Destinos con nombre (figuras): pagina y posicion vertical.
tops = {}
for page in doc:
    for link in page.get_links():
        name = link.get("nameddest")
        target = link.get("page")
        point = link.get("to")
        if name and isinstance(target, int) and target >= 0 and point is not None:
            # "to" viene en coordenadas PDF (origen abajo): se pasa a distancia desde arriba.
            tops[unquote(name)] = {"page": target + 1, "y_mm": round((height - point.y) / MM, 1)}
print(json.dumps({"pages": pages, "tops": tops}))
