import argparse
from pathlib import Path

from repair_docx_wt_newlines import repair_docx_wt_newlines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair a humanized DOCX by removing newline characters inside <w:t> nodes "
            "in word/document.xml (replacing CR/LF runs with an empty string)."
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
        help="Output .docx path. Defaults to <input>.repaired_rm_newlines.docx.",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip scanning output for remaining CR/LF inside <w:t> nodes.",
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
        output_path = input_path.with_suffix(input_path.suffix + ".repaired_rm_newlines.docx")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Core behavior: remove newline runs entirely.
    repair_docx_wt_newlines(
        input_path=input_path,
        output_path=output_path,
        replace_with="",
        validate=not args.no_validate,
    )


if __name__ == "__main__":
    main()

