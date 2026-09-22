"""Small compatibility shim for the documents-skill renderer on this host.

The packaged renderer imports the pdf2image API, while this workspace already
provides pypdfium2. Only the two renderer-used functions are implemented.
"""

from pathlib import Path

import pypdfium2 as pdfium


def pdfinfo_from_path(pdf_path, **_kwargs):
    document = pdfium.PdfDocument(str(pdf_path))
    if len(document) == 0:
        return {"Pages": 0}
    width, height = document[0].get_size()
    return {"Pages": len(document), "Page size": f"{width:g} x {height:g} pts"}


def convert_from_path(
    pdf_path,
    dpi=200,
    fmt="png",
    thread_count=1,
    output_folder=None,
    paths_only=False,
    output_file="page",
    **_kwargs,
):
    del thread_count
    if fmt.lower() != "png":
        raise ValueError("compatibility shim supports PNG output only")
    document = pdfium.PdfDocument(str(pdf_path))
    output = Path(output_folder or ".")
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    images = []
    scale = float(dpi) / 72.0
    for index in range(len(document)):
        image = document[index].render(scale=scale).to_pil()
        path = output / f"{output_file}-pdfium-{index + 1}.png"
        image.save(path)
        paths.append(str(path))
        images.append(image)
    return paths if paths_only else images
