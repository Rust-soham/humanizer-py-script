
import argparse
import re
import zipfile
from pathlib import Path
from typing import Optional

from lxml import etree
from texthumanize import humanize


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"


_LEADING_TRAILING_WS_RE = re.compile(r"^([ \t\r\n]*)(.*?)([ \t\r\n]*)$")
_PUNCT_ONLY_RE = re.compile(r"^[\W_]+$", re.UNICODE)


def _is_ancestor_math(el: etree._Element) -> bool:
    # Word math nodes live under the math namespace; skip their <w:t> so we don't
    # accidentally corrupt equations.
    parent = el.getparent()
    while parent is not None:
        if parent.tag.startswith(f"{{{MATH_NS}}}"):
            return True
        parent = parent.getparent()
    return False


def _is_ancestor_instr_text(el: etree._Element) -> bool:
    parent = el.getparent()
    while parent is not None:
        if parent.tag == f"{{{WORD_NS}}}instrText":
            return True
        parent = parent.getparent()
    return False


def _split_preserving_leading_trailing_ws(text: str) -> tuple[str, str, str]:
    m = _LEADING_TRAILING_WS_RE.match(text)
    if not m:
        # Fallback: shouldn't happen for normal Word text nodes.
        return "", text, ""
    return m.group(1), m.group(2), m.group(3)


def _should_skip_core_text(core: str, *, min_chars: int) -> bool:
    if core == "":
        return True
    if len(core) < min_chars:
        return True
    # Avoid trying to "humanize" punctuation-only segments.
    if _PUNCT_ONLY_RE.match(core.strip()):
        return True
    # If there are no letters at all, it's likely not natural language.
    if not any(ch.isalpha() for ch in core):
        return True
    return False


def humanize_docx(
    input_path: Path,
    output_path: Path,
    *,
    lang: str = "en",
    profile: str = "academic",
    intensity: Optional[int] = None,
    seed: int = 42,
    min_chars: int = 2,
) -> None:
    """
    Humanize DOCX body text while preserving Word formatting primitives.

    Implementation strategy:
    - Treat the DOCX as a ZIP container.
    - Parse `word/document.xml` and update only `<w:t>` elements (text nodes).
    - Skip `<w:t>` inside field instruction text (`w:instrText`) and inside
      Word math (`m:*`) nodes.
    - Repackage the DOCX by copying all ZIP parts unchanged except
      `word/document.xml`.

    Pitfall: Word often splits visible text across multiple runs/text nodes, so
    humanizing at the `<w:t>` (run-level) may reduce global coherence. This
    is the trade-off for keeping formatting boundaries intact.
    """

    input_path = input_path.resolve()
    output_path = output_path.resolve()

    word_document_member = "word/document.xml"

    with zipfile.ZipFile(input_path, "r") as zin:
        try:
            original_xml_bytes = zin.read(word_document_member)
        except KeyError as e:
            raise SystemExit(f"Missing {word_document_member} in DOCX: {input_path}") from e

        xml_root = etree.fromstring(original_xml_bytes)

        text_nodes = list(xml_root.iter(f"{{{WORD_NS}}}t"))

        processed = 0
        skipped = 0

        for t_el in text_nodes:
            if t_el.text is None:
                continue

            if _is_ancestor_instr_text(t_el) or _is_ancestor_math(t_el):
                skipped += 1
                continue

            leading_ws, core, trailing_ws = _split_preserving_leading_trailing_ws(t_el.text)
            if _should_skip_core_text(core, min_chars=min_chars):
                skipped += 1
                continue

            humanize_kwargs = {
                "text": core,
                "lang": lang,
                "profile": profile,
                "seed": seed,
            }
            if intensity is not None:
                humanize_kwargs["intensity"] = intensity

            result = humanize(**humanize_kwargs)
            t_el.text = f"{leading_ws}{result.text}{trailing_ws}"
            processed += 1

        new_xml_bytes = etree.tostring(
            xml_root,
            xml_declaration=True,
            encoding="UTF-8",
        )

        with zipfile.ZipFile(output_path, "w") as zout:
            for item in zin.infolist():
                if item.filename == word_document_member:
                    zout.writestr(item, new_xml_bytes)
                else:
                    zout.writestr(item, zin.read(item.filename))

    print(f"Saved humanized DOCX to: {output_path}")
    print(f"Updated <w:t> nodes: processed={processed}, skipped={skipped}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Humanize a DOCX by editing only `word/document.xml` <w:t> text nodes, "
            "skipping field instructions and math."
        )
    )
    parser.add_argument(
        "input",
        type=str,
        help="Path to the input .docx file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help=(
            "Output .docx path. "
            "Defaults to <input>.humanized.docx."
        ),
    )
    parser.add_argument(
        "--lang",
        type=str,
        default="en",
        help="Language code for the text (default: en).",
    )
    parser.add_argument(
        "--profile",
        type=str,
        default="academic",
        help=(
            'texthumanize processing profile (default: academic). '
            'Other options include chat, web, seo, docs, formal, marketing, social, email.'
        ),
    )
    parser.add_argument(
        "--intensity",
        type=int,
        default=None,
        help="Optional intensity (0–100). If omitted, texthumanize uses its profile default.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42).",
    )
    parser.add_argument(
        "--min-chars",
        type=int,
        default=2,
        help="Minimum character count for a <w:t> segment to be humanized.",
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
        output_path = input_path.with_name(input_path.stem + ".humanized.docx")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    humanize_docx(
        input_path=input_path,
        output_path=output_path,
        lang=args.lang,
        profile=args.profile,
        intensity=args.intensity,
        seed=args.seed,
        min_chars=args.min_chars,
    )


if __name__ == "__main__":
    main()

