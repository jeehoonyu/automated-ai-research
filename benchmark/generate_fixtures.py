from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def main() -> None:
    output = Path(__file__).resolve().parent / "fixtures"
    output.mkdir(parents=True, exist_ok=True)
    _visual_fixture(output / "synthetic-visual.pdf")
    _table_fixture(output / "synthetic-table.pdf")


def _visual_fixture(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=1, pageCompression=0)
    pdf.setTitle("Synthetic visual evidence benchmark")
    pdf.drawString(72, 750, "Synthetic visual benchmark with directly inspectable page provenance.")
    pdf.drawString(72, 730, "Figure 1. Vector comparison of method A and method B")
    pdf.rect(90, 390, 360, 250)
    pdf.line(110, 420, 220, 520)
    pdf.line(220, 520, 410, 590)
    pdf.showPage()

    raster = Image.new("RGB", (480, 320), "white")
    drawing = ImageDraw.Draw(raster)
    drawing.rectangle((50, 50, 430, 270), outline="black", width=8)
    drawing.ellipse((170, 90, 310, 230), fill="gray")
    buffer = BytesIO()
    raster.save(buffer, format="PNG", optimize=False)
    buffer.seek(0)
    pdf.drawImage(ImageReader(buffer), 72, 220, width=468, height=312)
    pdf.showPage()
    pdf.save()


def _table_fixture(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=1, pageCompression=0)
    pdf.setTitle("Synthetic table evidence benchmark")
    pdf.drawString(72, 750, "Table 1. Synthetic measurements for deterministic extraction")
    for x in (72, 240, 390, 520):
        pdf.line(x, 610, x, 720)
    for y in (610, 650, 685, 720):
        pdf.line(72, y, 520, y)
    for x, value in ((82, "Method"), (250, "Samples"), (400, "Reduction")):
        pdf.drawString(x, 696, value)
    for y, method, samples, reduction in (
        (662, "A", "120", "18 percent"),
        (622, "B", "120", "3 percent"),
    ):
        pdf.drawString(82, y, method)
        pdf.drawString(250, y, samples)
        pdf.drawString(400, y, reduction)
    pdf.save()


if __name__ == "__main__":
    main()
