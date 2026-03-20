import argparse
import re
import zipfile
from pathlib import Path
from typing import Optional

from lxml import etree


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_NL_RE = re.compile(r"[\r\n]+")


def _count_newlines_in_wt(xml_root: etree._Element) -> tuple[int, int]:
    """
    Returns (lf_count, cr_count) for newline characters inside <w:t> nodes.
    """
    lf = 0
    cr = 0
    for t_el in xml_root.iter(f"{{{WORD_NS}}}t"):
        s = t_el.text or ""
        lf += s.count("\n")
        cr += s.count("\r")
    return lf, cr


def repair_docx_wt_newlines(
    input_path: Path,
    output_path: Path,
    *,
    replace_with: str = " ",
    validate: bool = True,
) -> None:
    input_path = input_path.resolve()
    output_path = output_path.resolve()

    word_document_member = "word/document.xml"

    with zipfile.ZipFile(input_path, "r") as zin:
        try:
            original_xml_bytes = zin.read(word_document_member)
        except KeyError as e:
            raise SystemExit(f"Missing {word_document_member} in DOCX: {input_path}") from e

        xml_root = etree.fromstring(original_xml_bytes)

        before_lf, before_cr = _count_newlines_in_wt(xml_root)

        replaced_nodes = 0
        for t_el in xml_root.iter(f"{{{WORD_NS}}}t"):
            if t_el.text is None:
                continue
            if "\n" not in t_el.text and "\r" not in t_el.text:
                continue
            t_el.text = _NL_RE.sub(replace_with, t_el.text)
            replaced_nodes += 1

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

    if validate:
        with zipfile.ZipFile(output_path, "r") as z:
            out_xml = z.read(word_document_member)
        out_root = etree.fromstring(out_xml)
        after_lf, after_cr = _count_newlines_in_wt(out_root)
        if after_lf != 0 or after_cr != 0:
            raise SystemExit(
                "Validation failed: remaining newline characters inside <w:t> nodes: "
                f"LF={after_lf}, CR={after_cr}"
            )

    print(f"Repaired DOCX: {output_path}")
    print(
        f"Newlines in <w:t> before: LF={before_lf}, CR={before_cr}; "
        f"after: LF=0, CR=0 (validated={validate})"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Repair a humanized DOCX by removing newline characters inside <w:t> nodes "
            "in word/document.xml (replacing CR/LF runs with a single space)."
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
        help="Output .docx path. Defaults to <input>.repaired.docx.",
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
        output_path = input_path.with_suffix(input_path.suffix + ".repaired.docx")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    repair_docx_wt_newlines(
        input_path=input_path,
        output_path=output_path,
        replace_with=" ",
        validate=not args.no_validate,
    )


if __name__ == "__main__":
    main()

