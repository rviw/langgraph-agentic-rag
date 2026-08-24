"""Build small, real PDFs in memory so tests need no checked-in binaries."""


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def pdf_bytes(pages: list[str]) -> bytes:
    """Write a minimal single-font PDF whose pages hold extractable text."""

    objects: list[bytes] = []

    def add(body: str) -> int:
        objects.append(body.encode("latin-1"))
        return len(objects)

    font_id = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_ids: list[int] = []
    pages_id = len(objects) + 1 + 2 * len(pages)

    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({_escape(text)}) Tj ET"
        content_id = add(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        page_ids.append(
            add(
                f"<< /Type /Page /Parent {pages_id} 0 R "
                f"/MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            )
        )

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    add(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>")
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")

    out = bytearray(b"%PDF-1.7\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)
