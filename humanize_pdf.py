import argparse
import re
from pathlib import Path
from typing import Optional
import hashlib

from texthumanize import humanize


_LEADING_TRAILING_WS_RE = re.compile(r"^([ \t\r\n]*)(.*?)([ \t\r\n]*)$")
_PUNCT_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)


def _split_preserving_leading_trailing_ws(text: str) -> tuple[str, str, str]:
    m = _LEADING_TRAILING_WS_RE.match(text)
    if not m:
        return "", text, ""
    return m.group(1), m.group(2), m.group(3)


def _should_skip_core_text(core: str, *, min_chars: int) -> bool:
    if core == "":
        return True
    if len(core) < min_chars:
        return True
    if _PUNCT_ONLY_RE.match(core.strip()):
        return True
    if not any(ch.isalpha() for ch in core):
        return True
    return False


def _humanize_line(
    raw_line: str,
    *,
    lang: str,
    profile: str,
    intensity: Optional[int],
    seed: int,
    min_chars: int,
    humanize_cache: Optional[dict[tuple[str, str, str, Optional[int], int], str]] = None,
) -> str:
    leading_ws, core, trailing_ws = _split_preserving_leading_trailing_ws(raw_line)

    if _should_skip_core_text(core, min_chars=min_chars):
        return raw_line

    cache_key = (core, lang, profile, intensity, seed)
    if humanize_cache is not None and cache_key in humanize_cache:
        return f"{leading_ws}{humanize_cache[cache_key]}{trailing_ws}"

    humanize_kwargs = {"text": core, "lang": lang, "profile": profile, "seed": seed}
    if intensity is not None:
        humanize_kwargs["intensity"] = intensity

    result = humanize(**humanize_kwargs)
    if humanize_cache is not None:
        humanize_cache[cache_key] = result.text
    return f"{leading_ws}{result.text}{trailing_ws}"


def _looks_like_latex_line(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped:
        return False
    # Heuristic: if the line begins with a LaTeX command, keep it.
    # (Extracted PDF text typically doesn't preserve LaTeX source, but this
    # makes the tool safer if it does.)
    return stripped.startswith("\\") or stripped.startswith("%")


def humanize_pdf(
    input_path: Path,
    output_path: Path,
    *,
    lang: str = "en",
    profile: str = "academic",
    intensity: Optional[int] = None,
    seed: int = 42,
    min_chars: int = 2,
    min_text_chars: int = 50,
    segment_mode: str = "block",
    max_pages: Optional[int] = None,
    max_blocks: Optional[int] = None,
    scan_pages: Optional[int] = 3,
) -> None:
    """
    Humanize a PDF by redrawing extractable text into the same regions.

    Best-effort approach:
    - Uses PyMuPDF to extract text blocks/lines with bounding boxes.
    - Humanizes either line-by-line (`segment_mode="line"`) or block-level
      (`segment_mode="block"`) to reduce the number of model calls.
    - Covers the original line region with a white rectangle, then inserts the
      humanized text back into the bounding box.

    Limitations (cannot be fully avoided):
    - For scanned PDFs (no extractable text), extraction will be empty; we
      fail fast and ask for OCR upstream.
    - Visual fidelity (font, spacing, backgrounds) may differ, especially if
      the PDF uses unusual fonts/colors or if the bounding boxes don't align
      perfectly with the rendered glyphs.
    - This preserves the PDF structure (pages, vectors/images outside covered
      rectangles) but it does modify the page content streams.
    """

    try:
        import fitz  # PyMuPDF
    except ModuleNotFoundError as e:
        raise SystemExit(
            "PyMuPDF is required for PDF processing. Install with: pip install PyMuPDF"
        ) from e

    input_path = input_path.resolve()
    output_path = output_path.resolve()

    doc = fitz.open(str(input_path))
    total_text_chars = 0
    scan_cap = len(doc) if scan_pages is None else min(scan_pages, len(doc))
    for i in range(scan_cap):
        page = doc[i]
        # Use a sampled full text extraction as a more reliable signal than
        # dict-block types. Scanning only the first few pages makes progress
        # observable on large PDFs.
        page_text = page.get_text("text") or ""
        total_text_chars += len(page_text)

    if total_text_chars <= 1:
        raise SystemExit(
            "PDF text extraction seems empty. This tool works best for PDFs with embedded text. "
            "If your PDF is scanned, run OCR first and then retry."
        )
    if total_text_chars < min_text_chars:
        print(
            f"Warning: extracted text is small (chars={total_text_chars}). "
            f"Continuing anyway; you may need OCR if this PDF is scanned."
        )

    # Fallback font (only used if we can't extract an embedded font).
    font_name_fallback = "helv"

    # Cache extracted embedded fonts so we don't re-extract the same xref.
    # The files are written into a local cache directory under the project.
    font_cache_dir = (Path(__file__).parent / ".pdf_font_cache").resolve()
    font_cache_dir.mkdir(parents=True, exist_ok=True)
    fontfile_by_xref: dict[int, str] = {}
    # (page_number, span_font_name) -> fontfile
    fontfile_by_span_cache: dict[tuple[int, str], str] = {}

    # Cache humanization results for repeated blocks/lines within the same run.
    # With a fixed seed, texthumanize is deterministic for identical input text,
    # so caching can massively reduce runtime on repetitive PDFs.
    humanize_cache: dict[tuple[str, str, str, Optional[int], int], str] = {}

    def _insert_textbox_with_fit(
        *,
        page_obj,
        rect: "fitz.Rect",
        text: str,
        fontsize_initial: float,
        fontfile: Optional[str] = None,
        fontsize_min: float = 4.0,
        fontname: str = "helv",
        align: int = 0,
        color: tuple[float, float, float] = (0, 0, 0),
        max_iters: int = 10,
        shrink_factor: float = 0.92,
    ) -> float:
        """
        Insert text into `rect`, shrinking font size until all text fits.

        PyMuPDF `insert_textbox()` returns a float. When it's negative, the text
        did not fit. When it's >= 0, there is unused space remaining.
        """

        fontsize = float(fontsize_initial)
        last_ret: float = -1.0
        for _ in range(max_iters):
            if fontsize < fontsize_min:
                break

            # Clear any previous attempt within the region.
            page_obj.draw_rect(
                rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True
            )

            ret = page_obj.insert_textbox(
                rect,
                text,
                fontsize=fontsize,
                fontname=fontname,
                fontfile=fontfile,
                color=color,
                align=align,
            )
            last_ret = float(ret)
            if last_ret >= 0:
                return fontsize

            fontsize *= shrink_factor

        return fontsize

    def _inflate_rect(rect: "fitz.Rect", pad: float) -> "fitz.Rect":
        return fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)

    def _extract_fontfile_for_xref(doc_obj, xref: int) -> str:
        cached = fontfile_by_xref.get(xref)
        if cached is not None:
            return cached

        extracted = doc_obj.extract_font(xref)
        # PyMuPDF returns: (font_name, ext_1, ext_2, bytes)
        if not isinstance(extracted, tuple) or len(extracted) < 4:
            raise RuntimeError(f"Unexpected extract_font result for xref={xref}")

        font_name = extracted[0]
        font_bytes = extracted[3]
        ext = extracted[1] or "ttf"

        # Use a stable filename so repeated runs reuse cache files.
        digest = hashlib.sha256(f"{xref}:{font_name}".encode("utf-8")).hexdigest()[:12]
        out_path = font_cache_dir / f"{xref}_{digest}.{ext}"
        if not out_path.exists():
            out_path.write_bytes(font_bytes)

        fontfile_by_xref[xref] = str(out_path)
        return str(out_path)

    def _choose_fontfile_for_span(
        doc_obj, page_number: int, span_font_name: str
    ) -> Optional[str]:
        # Try cache first.
        cache_key = (page_number, span_font_name)
        cached = fontfile_by_span_cache.get(cache_key)
        if cached is not None:
            return cached

        page_fonts = doc_obj.get_page_fonts(page_number)
        # Each entry: (xref, type, subtype, name, psname, encoding)
        candidates = [(f[0], f[3].split("+")[-1]) for f in page_fonts]

        sf = (span_font_name or "").lower()
        is_bold = "bold" in sf
        is_italic = "ital" in sf
        family_times = "times" in sf
        family_courier = "cour" in sf

        def score(base_name: str) -> int:
            b = base_name.lower()
            s = 0
            if family_times and "times" in b:
                s += 5
            if family_courier and "cour" in b:
                s += 5
            if is_bold and "bold" in b:
                s += 2
            if is_italic and ("italic" in b or "ital" in b):
                s += 2
            # Prefer closer match when removing prefixes/suffixes.
            if sf.replace("-", "") in b.replace("-", ""):
                s += 3
            return s

        best_xref = None
        best_score = -1
        for xref, base_name in candidates:
            s = score(base_name)
            if s > best_score:
                best_score = s
                best_xref = xref

        if best_xref is None:
            # Let insert_textbox fall back to `fontname`.
            fontfile_by_span_cache[cache_key] = ""
            return None

        fontfile = _extract_fontfile_for_xref(doc_obj, int(best_xref))
        fontfile_by_span_cache[cache_key] = fontfile
        return fontfile

    processed = 0
    skipped = 0
    blocks_processed = 0
    blocks_skipped = 0
    blocks_seen = 0

    page_idx = 0
    for page in doc:
        if max_pages is not None and page_idx >= max_pages:
            break
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            # Best-effort: treat blocks that have lines/text as text blocks.
            # Some PDFs may label text blocks with a different `type`.
            if not block.get("lines") and not (block.get("text") or "").strip():
                continue
            block_bbox = block.get("bbox")
            if not block_bbox:
                continue

            # Derive block text from line->spans (more reliable than relying
            # on `block["text"]`, which can be empty for some PDFs).
            raw_lines: list[str] = []
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                raw_line = "".join((sp.get("text", "") or "") for sp in spans)
                raw_lines.append(raw_line)
            block_text = "\n".join(raw_lines).strip()
            if not block_text:
                continue
            blocks_seen += 1
            if max_blocks is not None and blocks_seen >= max_blocks:
                break

            # Humanize either per line (slower, better formatting stability) or
            # per block (faster, may change line breaks).
            new_block_text: str
            if segment_mode == "line":
                # Line mode: redraw each line into its own bbox to reduce
                # overlap and clipping (this is what usually fixes "missing"
                # sections like abstracts).
                for line in block.get("lines", []):
                    line_bbox = line.get("bbox")
                    if not line_bbox:
                        continue

                    spans = line.get("spans", [])
                    raw_line = "".join((sp.get("text", "") or "") for sp in spans)
                    if not raw_line:
                        continue

                    if _looks_like_latex_line(raw_line):
                        continue

                    # Choose the primary span for typography (font + size).
                    primary_span = None
                    for sp in spans:
                        if (sp.get("text") or "").strip():
                            primary_span = sp
                            break
                    if primary_span is None:
                        primary_span = spans[0] if spans else {}

                    primary_font = primary_span.get("font") or ""
                    primary_size = float(primary_span.get("size") or 11.0)
                    fontfile = _choose_fontfile_for_span(doc, page.number, primary_font)

                    humanized = _humanize_line(
                        raw_line,
                        lang=lang,
                        profile=profile,
                        intensity=intensity,
                        seed=seed,
                        min_chars=min_chars,
                        humanize_cache=humanize_cache,
                    )
                    if humanized.strip() == raw_line.strip():
                        skipped += 1
                        continue

                    rect = fitz.Rect(line_bbox)
                    # Inflate slightly to reduce unnecessary font shrinking caused by
                    # imperfect text bbox extraction.
                    pad = min(1.0, rect.height * 0.15)
                    draw_rect = _inflate_rect(rect, pad=pad)
                    fontsize_initial = max(4.0, primary_size)
                    _insert_textbox_with_fit(
                        page_obj=page,
                        rect=draw_rect,
                        text=humanized,
                        fontsize_initial=fontsize_initial,
                        fontsize_min=4.0,
                        fontname=font_name_fallback,
                        fontfile=fontfile,
                        align=0,
                        color=(0, 0, 0),
                    )

                    processed += 1

                blocks_processed += 1
            else:
                # Block mode: redraw the whole block once, but dynamically
                # shrink font size until the humanized text fits.
                #
                # Collapse internal whitespace to get a clean paragraph input
                # for the humanizer; `insert_textbox()` will re-wrap.
                core = " ".join(block_text.split())
                if _should_skip_core_text(core, min_chars=min_chars):
                    blocks_skipped += 1
                    continue

                cache_key = (core, lang, profile, intensity, seed)
                cached = humanize_cache.get(cache_key)
                if cached is None:
                    humanize_kwargs = {"text": core, "lang": lang, "profile": profile, "seed": seed}
                    if intensity is not None:
                        humanize_kwargs["intensity"] = intensity
                    result = humanize(**humanize_kwargs)
                    cached = result.text
                    humanize_cache[cache_key] = cached

                new_block_text = cached.rstrip("\n")
                if new_block_text.strip() == core.strip():
                    blocks_skipped += 1
                    continue

                rect = fitz.Rect(block_bbox)
                original_line_count = max(1, len(block.get("lines", [])))
                # Choose typography from the first available span in the block.
                primary_span = None
                for ln in block.get("lines", []):
                    for sp in ln.get("spans", []):
                        if (sp.get("text") or "").strip():
                            primary_span = sp
                            break
                    if primary_span is not None:
                        break
                if primary_span is None:
                    primary_span = {"size": 11.0, "font": ""}

                primary_font = primary_span.get("font") or ""
                primary_size = float(primary_span.get("size") or 11.0)
                fontfile = _choose_fontfile_for_span(doc, page.number, primary_font)

                pad = min(2.0, rect.height * 0.05)
                draw_rect = _inflate_rect(rect, pad=pad)
                fontsize_initial = max(4.0, primary_size)

                _insert_textbox_with_fit(
                    page_obj=page,
                    rect=draw_rect,
                    text=new_block_text,
                    fontsize_initial=fontsize_initial,
                    fontsize_min=4.0,
                    fontname=font_name_fallback,
                    fontfile=fontfile,
                    align=0,
                    color=(0, 0, 0),
                )

                processed += 1
                blocks_processed += 1

            if blocks_seen > 0 and blocks_seen % 100 == 0:
                print(
                    f"Progress: blocks_seen={blocks_seen}, blocks_processed={blocks_processed}, "
                    f"blocks_skipped={blocks_skipped}, processed_segments={processed}, skipped_segments={skipped}"
                )

        page_idx += 1
        if max_blocks is not None and blocks_seen >= max_blocks:
            break

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(output_path))
    doc.close()

    print(f"Saved humanized PDF to: {output_path}")
    print(
        f"Redraw pass: processed_segments={processed}, skipped_segments={skipped}, "
        f"segment_mode={segment_mode}, blocks_processed={blocks_processed}, blocks_skipped={blocks_skipped}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Humanize a PDF by extracting embedded text and re-drawing the "
            "humanized text back into the same page regions."
        )
    )
    parser.add_argument("input", type=str, help="Path to the input .pdf file.")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help="Output .pdf path. Defaults to <input>.humanized.pdf",
    )
    parser.add_argument("--lang", type=str, default="en", help="Language code (default: en).")
    parser.add_argument(
        "--profile",
        type=str,
        default="academic",
        help=(
            "texthumanize profile (default: academic). "
            "Other options: chat, web, seo, docs, formal, marketing, social, email."
        ),
    )
    parser.add_argument(
        "--intensity",
        type=int,
        default=None,
        help="Optional intensity (0-100). If omitted, texthumanize uses its profile default.",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42).")
    parser.add_argument(
        "--min-chars",
        type=int,
        default=2,
        help="Minimum segment length to humanize (default: 2).",
    )
    parser.add_argument(
        "--min-text-chars",
        type=int,
        default=50,
        help="Warning threshold if extracted PDF text is smaller than this (default: 50).",
    )
    parser.add_argument(
        "--segment-mode",
        type=str,
        choices=["block", "line"],
        default="block",
        help=(
            "How to split work before humanization. "
            "`block` reduces model calls (faster, may change line breaks). "
            "`line` preserves line count more closely (slower)."
        ),
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional safety limit for debugging (process only first N pages).",
    )
    parser.add_argument(
        "--max-blocks",
        type=int,
        default=None,
        help="Optional safety limit for debugging (process only first N text blocks).",
    )
    parser.add_argument(
        "--scan-pages",
        type=int,
        default=3,
        help=(
            "How many pages to scan before starting processing (default: 3). "
            "Use -1 to scan all pages."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file():
        raise SystemExit(f"Input file not found: {input_path}")

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        output_path = input_path.with_suffix(".humanized.pdf")

    humanize_pdf(
        input_path=input_path,
        output_path=output_path,
        lang=args.lang,
        profile=args.profile,
        intensity=args.intensity,
        seed=args.seed,
        min_chars=args.min_chars,
        min_text_chars=args.min_text_chars,
        segment_mode=args.segment_mode,
        max_pages=args.max_pages,
        max_blocks=args.max_blocks,
        scan_pages=None if args.scan_pages == -1 else args.scan_pages,
    )


if __name__ == "__main__":
    main()

