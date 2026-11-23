#!/usr/bin/env python3
"""Audit text font sizes used by PDF content-stream ``Tf`` operators.

This dependency-free check catches reduced mathtext superscripts/subscripts and
other glyph runs that can fall below a journal font-size floor even when the
parent matplotlib ``fontsize`` is compliant. It supports plain and FlateDecode
content streams, which covers normal matplotlib PDF output.

IMPORTANT LIMITATION — declared size != rendered size.
A ``Tf`` operand is the font size *before* the text/graphics matrices apply. A
run declared at 12 pt but scaled by a ``cm``/``Tm`` (or a Form XObject ``/Matrix``)
of 0.4 renders at ~4.8 pt while this scanner still reports 12 pt. That would
silently PASS an undersized figure, so the audit also reports whether such
scaling operators are present (``scale_operators`` / ``scaling_present``) and
warns loudly when they are. Treat a PASS on a file with scaling present as
UNVERIFIED, not as compliant.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path


STREAM_START = re.compile(rb"stream\r?\n")
TF_OPERATOR = re.compile(
    rb"/([^\s/<>]+)\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?)\s+Tf\b"
)


@dataclass(frozen=True)
class TextRun:
    stream: int
    font: str
    size_pt: float


def decoded_streams(data: bytes) -> tuple[list[bytes], list[bytes], list[str]]:
    """Return (decoded payloads, their stream dictionaries, warnings)."""
    streams: list[bytes] = []
    dictionaries: list[bytes] = []
    warnings: list[str] = []
    cursor = 0
    stream_number = 0
    while True:
        match = STREAM_START.search(data, cursor)
        if not match:
            break
        stream_number += 1
        end = data.find(b"endstream", match.end())
        if end < 0:
            warnings.append(f"stream {stream_number} has no endstream marker")
            break
        # Keep the raw stream bytes. zlib accepts PDF's trailing line break,
        # while stripping could accidentally remove a legitimate compressed
        # byte that happens to equal CR or LF.
        payload = data[match.end() : end]
        header = data[max(0, match.start() - 2048) : match.start()]
        dictionary_start = header.rfind(b"<<")
        dictionary = header[dictionary_start:] if dictionary_start >= 0 else header
        if b"/FlateDecode" in dictionary:
            try:
                payload = zlib.decompress(payload)
            except zlib.error as exc:
                warnings.append(f"stream {stream_number} FlateDecode failed: {exc}")
                cursor = end + len(b"endstream")
                continue
        elif b"/Filter" in dictionary:
            warnings.append(f"stream {stream_number} uses an unsupported PDF filter")
            cursor = end + len(b"endstream")
            continue
        streams.append(payload)
        dictionaries.append(dictionary)
        cursor = end + len(b"endstream")
    return streams, dictionaries, warnings


_NUM = rb"(-?(?:\d+\.?\d*|\.\d+))"
_CM_OP = re.compile(
    _NUM + rb"\s+" + _NUM + rb"\s+" + _NUM + rb"\s+"
    + _NUM + rb"\s+" + _NUM + rb"\s+" + _NUM + rb"\s+cm\b"
)
_TM_OP = re.compile(
    _NUM + rb"\s+" + _NUM + rb"\s+" + _NUM + rb"\s+"
    + _NUM + rb"\s+" + _NUM + rb"\s+" + _NUM + rb"\s+Tm\b"
)
_SCALE_TOLERANCE = 1e-3


def _has_nonidentity_scale(match: re.Match) -> bool:
    """True when a cm/Tm [a b c d e f] matrix scales on either axis.

    Effective scale is sqrt(a^2+b^2) horizontally and sqrt(c^2+d^2) vertically, so
    pure translation (a=d=1, b=c=0) and pure rotation (a=d=cos, b=-c=sin) both
    report 1.0 and are correctly ignored — only real scaling is flagged.
    """
    try:
        a, b, c, d = (float(match.group(i)) for i in (1, 2, 3, 4))
    except (TypeError, ValueError):
        return False
    sx = (a * a + b * b) ** 0.5
    sy = (c * c + d * d) ** 0.5
    return abs(sx - 1.0) > _SCALE_TOLERANCE or abs(sy - 1.0) > _SCALE_TOLERANCE


def scan_scale_operators(streams: list[bytes], dictionaries: list[bytes]) -> dict[str, int]:
    """Count operators that can actually SCALE already-declared text.

    Only non-identity scaling counts: matplotlib emits hundreds of translation-only
    ``cm`` operators (one per text run), so counting every ``cm`` would flag every
    normal figure and carry no information.
    """
    cm = tm = form_matrix = 0
    for stream in streams:
        if b"Tf" not in stream:
            continue
        cm += sum(1 for m in _CM_OP.finditer(stream) if _has_nonidentity_scale(m))
        tm += sum(1 for m in _TM_OP.finditer(stream) if _has_nonidentity_scale(m))
    for dictionary in dictionaries:
        if b"/FormType" in dictionary and b"/Matrix" in dictionary:
            form_matrix += 1
    return {"cm": cm, "Tm": tm, "form_matrix": form_matrix}


def audit_pdf(data: bytes, minimum_pt: float = 5.0) -> dict[str, object]:
    streams, dictionaries, warnings = decoded_streams(data)
    runs: list[TextRun] = []
    for stream_index, stream in enumerate(streams, 1):
        for match in TF_OPERATOR.finditer(stream):
            try:
                font = match.group(1).decode("ascii", errors="replace")
                size = float(match.group(2))
            except ValueError:
                continue
            if size > 0:
                runs.append(TextRun(stream=stream_index, font=font, size_pt=size))
    below = [run for run in runs if run.size_pt < minimum_pt]
    scale_operators = scan_scale_operators(streams, dictionaries)
    scaling_present = any(scale_operators.values())
    if scaling_present:
        warnings.append(
            "scaling operators present "
            f"(cm={scale_operators['cm']}, Tm={scale_operators['Tm']}, "
            f"form_matrix={scale_operators['form_matrix']}): declared Tf sizes are "
            "NOT rendered sizes — a PASS here is UNVERIFIED, confirm the actual size "
            "on the rendered page"
        )
    return {
        "auditable": bool(runs),
        "minimum_required_pt": minimum_pt,
        "minimum_found_pt": min((run.size_pt for run in runs), default=None),
        "text_run_count": len(runs),
        "below_minimum_count": len(below),
        "below_minimum": [asdict(run) for run in below],
        "scale_operators": scale_operators,
        "scaling_present": scaling_present,
        "warnings": warnings,
    }


def render_text(path: Path, result: dict[str, object]) -> str:
    lines = [
        "Nature Figure PDF Text Audit",
        f"pdf: {path}",
        f"minimum required: {result['minimum_required_pt']:g} pt",
    ]
    if not result["auditable"]:
        lines.append("verdict: NOT AUDITABLE — no supported Tf text operators were found")
    else:
        scaling = bool(result.get("scaling_present"))
        if result["below_minimum_count"]:
            verdict = "FAIL"
        elif scaling:
            verdict = "UNVERIFIED"      # 声明字号 ≠ 渲染字号，不能给 PASS
        else:
            verdict = "PASS"
        lines.extend(
            [
                f"minimum found: {result['minimum_found_pt']:g} pt",
                f"text runs: {result['text_run_count']}",
                f"below minimum: {result['below_minimum_count']}",
                f"verdict: {verdict}",
            ]
        )
        if scaling:
            ops = result.get("scale_operators") or {}
            lines.append(
                "  scaling present: cm={cm} Tm={Tm} form_matrix={form_matrix} "
                "— declared Tf sizes are not rendered sizes; verify on the rendered page".format(
                    cm=ops.get("cm", 0), Tm=ops.get("Tm", 0),
                    form_matrix=ops.get("form_matrix", 0),
                )
            )
    for run in result["below_minimum"]:
        lines.append(f"  - stream {run['stream']}: /{run['font']} {run['size_pt']:g} Tf")
    for warning in result["warnings"]:
        lines.append(f"warning: {warning}")
    lines.append("note: Tf scanning does not replace final-size visual inspection or account for every PDF transform")
    return "\n".join(lines)


def _self_test() -> int:
    """Prove the scaling guard actually fires, and that clean PDFs still PASS."""
    def build(content: bytes) -> bytes:
        objs = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
            + content + b"endstream",
        ]
        out = bytearray(b"%PDF-1.4\n")
        offsets = []
        for i, o in enumerate(objs, 1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
        for off in offsets:
            out += f"{off:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode()
        return bytes(out)

    clean = build(
        b"BT /F1 7 Tf 72 700 Td (seven pt) Tj ET\n"
        b"1 0 0 1 10 20 cm BT /F1 7 Tf 0 0 Td (moved only) Tj ET\n"
    )
    scaled = build(
        b"BT /F1 12 Tf 72 700 Td (declared twelve) Tj ET\n"
        b"q 0.4 0 0 0.4 72 650 cm BT /F1 12 Tf 0 0 Td (scaled 0.4) Tj ET Q\n"
    )
    tiny = build(b"BT /F1 4 Tf 72 700 Td (four pt) Tj ET\n")

    ok = True
    r_clean = audit_pdf(clean, minimum_pt=6.0)
    if r_clean["scaling_present"]:
        print("FAIL: translation-only cm was misread as scaling")
        ok = False
    if not r_clean["auditable"] or r_clean["below_minimum_count"]:
        print(f"FAIL: clean 7pt sample not clean: {r_clean}")
        ok = False
    if r_clean["minimum_found_pt"] != 7.0:
        print(f"FAIL: clean sample size read as {r_clean['minimum_found_pt']}, expected 7")
        ok = False

    r_scaled = audit_pdf(scaled, minimum_pt=6.0)
    if not r_scaled["scaling_present"]:
        print("FAIL: 0.4-scaled text did NOT raise the scaling flag (blind spot open)")
        ok = False
    # The scaled sample must NOT be reported as compliant: its worst run renders at
    # 4.8pt while the declared size is 12pt, so only UNVERIFIED is honest.
    if r_scaled["scaling_present"] and r_scaled["below_minimum_count"] == 0:
        print("ok: scaled sample reports UNVERIFIED (declared 12pt, renders 4.8pt)")

    r_tiny = audit_pdf(tiny, minimum_pt=6.0)
    if r_tiny["below_minimum_count"] != 1:
        print(f"FAIL: 4pt text not caught: {r_tiny['below_minimum_count']}")
        ok = False

    print("audit_pdf_text self-test: " + ("PASS" if ok else "FAIL")
          + " (3 cases: clean/translation-only, 0.4x scaled, 4pt undersized)")
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path, nargs="?", help="exported PDF figure")
    parser.add_argument("--min-pt", type=float, default=5.0, help="minimum allowed Tf font size in points")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--self-test", action="store_true",
                        help="run the built-in scaling/undersize guard checks and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return _self_test()
    if args.pdf is None:
        build_parser().error("a PDF path is required unless --self-test is used")
    if args.min_pt <= 0:
        print("error: --min-pt must be positive", file=sys.stderr)
        return 2
    try:
        data = args.pdf.read_bytes()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not data.startswith(b"%PDF-"):
        print(f"error: not a PDF file: {args.pdf}", file=sys.stderr)
        return 2
    result = audit_pdf(data, minimum_pt=args.min_pt)
    if args.json:
        print(json.dumps({"pdf": str(args.pdf), **result}, indent=2, ensure_ascii=False))
    else:
        print(render_text(args.pdf, result))
    if not result["auditable"]:
        return 2
    if result["below_minimum_count"]:
        return 1
    if result.get("scaling_present"):
        return 3          # 声明字号可信度不足：未验证，不等于通过
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
