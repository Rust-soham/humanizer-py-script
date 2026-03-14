import argparse
from pathlib import Path
from typing import Optional

from texthumanize import humanize, humanize_chunked


def _looks_like_latex(text: str) -> bool:
    """
    Heuristic: detect if the document is a LaTeX source (e.g., IEEEtran template).
    """
    lines = text.splitlines()
    if not lines:
        return False
    first_nonempty = next((ln for ln in lines if ln.strip()), "")
    return first_nonempty.lstrip().startswith(r"\documentclass")


def _humanize_plain_text(
    raw_text: str,
    *,
    lang: str,
    profile: str,
    intensity: Optional[int],
    seed: int,
    chunk_size: int,
):
    """
    Default mode for non-LaTeX: preserve line structure and humanize each
    non-empty line independently so large documents do not hit internal
    texthumanize timeouts.
    """
    lines = raw_text.splitlines(keepends=False)
    out_lines = []

    for line in lines:
        stripped = line.lstrip()

        if not stripped:
            out_lines.append(line)
            continue

        humanize_kwargs = {
            "text": stripped,
            "lang": lang,
            "profile": profile,
            "seed": seed,
        }
        if intensity is not None:
            humanize_kwargs["intensity"] = intensity

        result = humanize(**humanize_kwargs)
        leading_ws = line[: len(line) - len(stripped)]
        out_lines.append(f"{leading_ws}{result.text}")

    class _Result:
        def __init__(self, text: str):
            self.text = text
            self.change_ratio = None
            self.quality_score = None

    return _Result("\n".join(out_lines))


def _humanize_latex_preserve_structure(
    raw_text: str,
    *,
    lang: str,
    profile: str,
    intensity: Optional[int],
    seed: int,
):
    """
    LaTeX-aware mode: preserve all LaTeX commands/environments and only humanize
    prose lines (content) so that the template and formatting stay intact.
    """
    lines = raw_text.splitlines(keepends=False)
    out_lines = []

    for line in lines:
        stripped = line.lstrip()

        # Preserve LaTeX structure and math exactly:
        if (
            not stripped
            or stripped.startswith("%")
            or stripped.startswith("\\")
        ):
            out_lines.append(line)
            continue

        # For prose lines (no leading LaTeX command), humanize the content.
        # We pass a single line at a time to keep line structure.
        humanize_kwargs = {
            "text": stripped,
            "lang": lang,
            "profile": profile,
            "seed": seed,
        }
        # Only pass intensity if explicitly set; texthumanize does not accept None.
        if intensity is not None:
            humanize_kwargs["intensity"] = intensity

        result = humanize(**humanize_kwargs)
        # Preserve original leading whitespace indentation.
        leading_ws = line[: len(line) - len(stripped)]
        out_lines.append(f"{leading_ws}{result.text}")

    # We mimic the humanize_chunked return shape with a lightweight object.
    class _Result:
        def __init__(self, text: str):
            self.text = text
            # Per-line processing, so global change/quality metrics are unknown.
            self.change_ratio = None
            self.quality_score = None

    return _Result("\n".join(out_lines))


def humanize_file(
    input_path: Path,
    output_path: Path,
    lang: str = "en",
    profile: str = "academic",
    intensity: Optional[int] = None,
    seed: int = 42,
    chunk_size: int = 3000,
) -> None:
    """
    Humanize a full research-paper-style text file using texthumanize.

    - For plain-text papers: use humanize_chunked() to process the whole document.
    - For LaTeX IEEE-style papers: keep LaTeX commands/structure and only
      humanize prose lines so the template and formatting remain intact.
    """
    raw_text = input_path.read_text(encoding="utf-8")

    if _looks_like_latex(raw_text):
        result = _humanize_latex_preserve_structure(
            raw_text,
            lang=lang,
            profile=profile,
            intensity=intensity,
            seed=seed,
        )
    else:
        result = _humanize_plain_text(
            raw_text,
            lang=lang,
            profile=profile,
            intensity=intensity,
            seed=seed,
            chunk_size=chunk_size,
        )

    output_path.write_text(result.text, encoding="utf-8")

    change_ratio = getattr(result, "change_ratio", None)
    quality_score = getattr(result, "quality_score", None)

    print(f"Saved humanized text to: {output_path}")
    if change_ratio is not None:
        print(f"Change ratio: {change_ratio:.2f}")
    if quality_score is not None:
        print(f"Quality score: {quality_score:.1f}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Humanize a formatted research-paper .txt file using texthumanize "
            "with an academic profile."
        )
    )
    parser.add_argument(
        "input",
        type=str,
        help="Path to the input .txt file (e.g. whole.txt).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help=(
            "Path to the output .txt file. "
            "Defaults to <input>.humanized.txt in the same folder."
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
            "texthumanize processing profile (default: academic). "
            "Other options include chat, web, seo, docs, formal, marketing, social, email."
        ),
    )
    parser.add_argument(
        "--intensity",
        type=int,
        default=None,
        help=(
            "Optional intensity (0–100). If omitted, texthumanize uses "
            "its profile-specific default (academic ≈ 25)."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic output (default: 42).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=3000,
        help=(
            "Approximate character chunk size for internal splitting. "
            "Increase for fewer, larger chunks; decrease for smaller ones."
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
        output_path = input_path.with_suffix(input_path.suffix + ".humanized.txt")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    humanize_file(
        input_path=input_path,
        output_path=output_path,
        lang=args.lang,
        profile=args.profile,
        intensity=args.intensity,
        seed=args.seed,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()

