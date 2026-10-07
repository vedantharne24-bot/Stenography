"""Render the research-comparison JSON files into docs/experiments/README.md (between markers).

    python -m pipeline.summarize_experiments

Reads docs/experiments/technique_comparison_*.json (written by run_experiments.py) so the
published tables are generated from measured results, never transcribed by hand.
"""

from __future__ import annotations

import json
import re

from pipeline.common import ROOT

DOCS = ROOT / "docs" / "experiments"


def table(result: dict) -> list[str]:
    s = result["summary"]
    algos = ("lsb", "dct", "dwt")
    rows = [
        ("Payload embedded", lambda a: f"{s[a]['payload_bytes']:.0f} B"),
        ("Capacity", lambda a: f"{s[a]['capacity_bytes']:.0f} B ({s[a]['capacity_bpp']:.3f} bpp)"),
        ("PSNR", lambda a: f"{s[a]['psnr']:.2f} dB"),
        ("SSIM", lambda a: f"{s[a]['ssim']:.4f}"),
        ("Extraction success", lambda a: f"{s[a]['extraction_success'] * 100:.1f}%"),
        ("AI detection (StegoNet)", lambda a: f"{s[a]['detection_rate'] * 100:.1f}%"),
        ("Survival over attack suite", lambda a: f"{s[a]['robustness'] * 100:.1f}%"),
        ("Embed / extract time", lambda a: f"{s[a]['embed_ms']:.1f} / {s[a]['extract_ms']:.1f} ms"),
        ("Balance score", lambda a: f"{result['balance_score'][a]:.2f}"),
    ]
    out = ["| Metric | LSB | DCT | DWT |", "|---|---|---|---|"]
    out += [f"| {label} | " + " | ".join(fn(a) for a in algos) + " |" for label, fn in rows]
    return out


def main() -> None:
    sections = []
    for kind, title in (("absolute", "Same message for every technique"), ("relative", "Payload relative to each technique's capacity")):
        files = sorted(DOCS.glob(f"technique_comparison_{kind}_*.json"))
        if not files:
            continue
        r = json.loads(files[-1].read_text(encoding="utf-8"))
        cfg = r["config"]
        payload = f"{cfg['absolute_bytes']} bytes" if kind == "absolute" else f"{cfg['relative'] * 100:.0f} % of capacity"
        sections += [
            f"### {title} — {payload}, {cfg['images']} held-out images",
            "",
            *table(r),
            "",
            f"Cover false-positive rate on the same images: {r['cover_false_positive_rate'] * 100:.2f} %.",
            "",
            f"> {r['answer']}",
            "",
        ]
    block = "\n".join(sections).rstrip() + "\n"
    readme = DOCS / "README.md"
    text = readme.read_text(encoding="utf-8")
    marker = "<!-- FINDINGS:START -->\n{}<!-- FINDINGS:END -->"
    if "<!-- FINDINGS:START -->" in text:
        text = re.sub(r"<!-- FINDINGS:START -->.*?<!-- FINDINGS:END -->", marker.format(block), text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n## Research findings (LSB vs DCT vs DWT)\n\n" + marker.format(block) + "\n"
    readme.write_text(text, encoding="utf-8")
    print(block)


if __name__ == "__main__":
    main()
