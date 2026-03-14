import argparse
from pathlib import Path
from typing import Optional

from texthumanize import humanize


def humanize_plain_file(
    input_path: Path,
    output_path: Path,
    lang: str = "en",
    profile: str = "academic",
    intensity: Optional[int] = None,
    seed: int = 42,
) -> None:
    """
    Humanize a plain-text academic document while preserving paragraph structure.

    - Treats the file as pure text (no LaTeX awareness).
    - Splits on blank lines into paragraphs.
    - Humanizes each non-empty paragraph as a unit using texthumanize.
    - Keeps the same paragraph boundaries in the output.
    """
    raw_text = input_path.read_text(encoding="utf-8")

    # Split into paragraphs separated by one or more blank lines.
    lines = raw_text.splitlines(keepends=False)
    paragraphs: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if line.strip() == "":
            if current:
                paragraphs.append(current)
                current = []
            paragraphs.append([])  # Represent a blank-line paragraph
        else:
            current.append(line)
    if current:
        paragraphs.append(current)

    out_lines: list[str] = []

    for para in paragraphs:
        if not para:
            # Blank paragraph: preserve a single blank line
            out_lines.append("")
            continue

        # Join the original paragraph lines with spaces to form one logical paragraph.
        original_para_text = " ".join(line.strip() for line in para)

        humanize_kwargs = {
            "text": original_para_text,
            "lang": lang,
            "profile": profile,
            "seed": seed,
        }
        if intensity is not None:
            humanize_kwargs["intensity"] = intensity

        result = humanize(**humanize_kwargs)

        # Write the humanized paragraph as a single line to keep structure simple.
        out_lines.append(result.text)

    output_text = "\n".join(out_lines)
    output_path.write_text(output_text, encoding="utf-8")

    print(f"Saved humanized text to: {output_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Humanize a plain-text academic file (no LaTeX) using texthumanize "
            "with an academic profile, preserving paragraph boundaries."
        )
    )
    parser.add_argument(
        "input",
        type=str,
        help="Path to the input plain-text file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        help=(
            "Path to the output file. "
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
        help="texthumanize processing profile (default: academic).",
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

    humanize_plain_file(
        input_path=input_path,
        output_path=output_path,
        lang=args.lang,
        profile=args.profile,
        intensity=args.intensity,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()

