---
name: latex-paper-humanize
description: Humanizes LaTeX research papers using texthumanize while preserving IEEE-style template commands and formatting. Use when the user provides a .tex/.txt LaTeX paper (e.g., IEEEtran) and asks to humanize or de-AI the content without breaking the LaTeX structure.
---

# LaTeX Paper Humanization

## Purpose

This skill describes how to safely humanize the **prose content** of LaTeX research papers (especially IEEEtran-style documents) using the `texthumanize` Python library, while **preserving all LaTeX commands, environments, math, and overall formatting**.

Use this skill when:

- The input file is a LaTeX source or LaTeX-like `.txt` export (starts with `\documentclass`, contains `\begin{document}`, `\section{...}`, etc.).
- The user explicitly says the **template/formatting must not change**, only the wording of the content.
- The user wants AI-style text reduced or humanized for academic writing.

## High-Level Rules

1. **Never modify LaTeX commands or environments.**
   - Do not change or remove lines starting with `\` (e.g., `\documentclass`, `\usepackage`, `\section`, `\begin{...}`, `\end{...}`, `\title`, `\author`, `\maketitle`, math environments).
   - Do not modify lines starting with `%` (comments).
   - Do not alter math environments (`\[...\]`, `\(...\)`, `equation`, `align`, etc.).
2. **Only humanize plain prose lines.**
   - Lines that do not start with `\` or `%` are treated as natural-language content.
   - These lines are fed to `texthumanize` with `profile="academic"` (or another profile if the user requests).
3. **Preserve formatting and line structure.**
   - Keep the same line order and blank lines.
   - Preserve leading whitespace for each line.
4. **Do not promise detector bypass.**
   - `texthumanize` is a style-normalization tool; it cannot guarantee beating all external AI detectors (GPTZero, Turnitin, Originality.ai, etc.).

## Implementation Pattern

When editing code or writing scripts for this workflow, follow this pattern:

1. **Detect LaTeX documents**

   - Heuristic: if the first non-empty line starts with `\documentclass`, treat the file as LaTeX.

2. **Per-line processing for LaTeX**

   - For each line:
     - Let `stripped = line.lstrip()`.
     - If `stripped` is empty, or `stripped.startswith("%")`, or `stripped.startswith("\\")`:
       - **Leave the line unchanged** (copy it directly to output).
     - Otherwise:
       - Treat `stripped` as prose.
       - Build kwargs for `texthumanize.humanize`:
         - Required: `text=stripped, lang="en", profile="academic", seed=<int>`.
         - **Only include** `intensity` in kwargs if the user explicitly sets it to an integer.
           - Do **not** pass `intensity=None` (it causes a `TypeError: '<' not supported between instances of 'NoneType' and 'int'` in `texthumanize`).
       - Reconstruct the line as `leading_whitespace + result.text`.

3. **Plain-text documents**

   - If the document does **not** look like LaTeX, prefer **per-line humanization** to avoid internal timeouts in `texthumanize.humanize_chunked`:
     - Split into lines, preserve ordering and whitespace.
     - For each non-empty line:
       - Call `texthumanize.humanize` with the same kwargs pattern as in step 2 (only pass `intensity` when it is an actual integer).
     - Rejoin lines with `\n` so the original formatting is preserved.

4. **CLI integration (recommended)**

   - Prefer using/maintaining a script similar to `humanize_paper.py` in the project:
     - It should:
       - Read the entire file as UTF-8.
       - Detect LaTeX vs plain text (per rule 1).
       - For LaTeX: apply per-line humanization as in rule 2.
       - For plain text: use `humanize_chunked` as in rule 3.
       - Write the result to an output `.txt`/`.tex` without changing the overall structure.

## Usage Workflow (for this project)

When the user wants to humanize a LaTeX paper in this repository:

1. **Install dependencies (once):**
   - Run: `pip install -r requirements.txt` from the project root.
2. **Place the LaTeX paper file** (e.g., `aicontent1.txt` or `.tex`) in the project.
3. **Run the humanizer script:**
   - Example:
     - `python humanize_paper.py aicontent1.txt`
   - This should:
     - Detect it as LaTeX (`\documentclass`).
     - Preserve all LaTeX commands, math, and formatting.
     - Humanize only the prose lines using the academic profile.
     - Produce `aicontent1.txt.humanized.txt` (or a custom output file if specified).
4. **Review the output manually**:
   - Check that:
     - LaTeX compiles (no missing backslashes/braces).
     - Sections, environments, and math are unchanged.
     - The prose reads naturally and maintains academic tone.

## Examples

### Example 1: LaTeX prose line

Input line:

```tex
The proposed framework also features a hybrid attention-based architecture to enhance the effectiveness of diagnostic and represent features.
```

Processing:

- Line does **not** start with `\` or `%` → treat as prose.
- Humanize with `texthumanize.humanize(..., profile="academic")`.

Output line (conceptual):

```tex
The proposed framework adopts a hybrid attention-based architecture that strengthens both diagnostic reliability and feature representation.
```

### Example 2: LaTeX structure line

Input line:

```tex
\section{Introduction}
```

Processing:

- Line **starts with `\`** → **do not modify**.

Output line:

```tex
\section{Introduction}
```

### Example 3: Math environment

Input lines:

```tex
\[
Accuracy = \frac{TP + TN}{TP + TN + FP + FN}
\]
```

Processing:

- All lines start with `\` → **do not modify any of them**.

Output lines are identical to input.

