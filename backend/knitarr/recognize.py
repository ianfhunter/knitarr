"""Debug CLI: python -m knitarr.recognize chart.png -o ./out"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from knitarr.services.chart_recognize import recognize_chart_image


def _load(path: Path, page: int) -> Image.Image:
    if path.suffix.lower() == ".pdf":
        import fitz

        with fitz.open(path) as doc:
            idx = max(0, page - 1)
            if idx >= doc.page_count:
                raise ValueError(f"PDF page {page} out of range (1–{doc.page_count})")
            pix = doc[idx].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    with Image.open(path) as im:
        return im.convert("RGB")


def main() -> None:
    parser = argparse.ArgumentParser(description="Recognise an existing cross-stitch chart (grid + symbols).")
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, default=Path("chart-recognition"))
    parser.add_argument("--page", type=int, default=1, help="PDF page (1-based)")
    args = parser.parse_args()

    im = _load(args.input, args.page)
    result = recognize_chart_image(im, max_width=400, max_colors=48)
    args.output.mkdir(parents=True, exist_ok=True)
    payload = {
        "width": result.width,
        "height": result.height,
        "mode": result.mode,
        "source": result.source,
        "clusters": result.clusters,
        "low_confidence": result.low_confidence,
        "stitch_count": len(result.stitches),
        "stitches": [
            {
                "x": s.x,
                "y": s.y,
                "rgb": list(s.rgb),
                "confidence": round(s.confidence, 3),
                "symbol_id": s.cluster_id,
                "kind": s.kind,
            }
            for s in result.stitches
        ],
    }
    (args.output / "chart.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if result.annotated is not None:
        result.annotated.save(args.output / "annotated.png")
    print(
        f"{result.mode} {result.width}×{result.height} "
        f"{len(result.stitches)} stitches, {result.clusters} symbols, "
        f"{result.low_confidence} low-confidence → {args.output}"
    )


if __name__ == "__main__":
    main()
