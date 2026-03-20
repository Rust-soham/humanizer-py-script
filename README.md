## Humanize Research Paper Text (`texthumanize` CLI)

This mini-project lets you take a full research-paper-style `.txt` file (for example, exported from a paper editing site) and run it through the [`texthumanize`](https://pypi.org/project/texthumanize/) library using its **academic** profile.

The script:

- **Preserves the overall formatting** of your text file (headings, spacing, etc.) while normalizing the language.
- Uses `humanize_chunked()` so **very long papers** can be processed safely.
- Is configured for **formal academic style** by default (`profile="academic"`).

> **Important limitation:** Neither this script nor `texthumanize` can *guarantee* that your text will evade all external AI detectors (GPTZero, Turnitin, Originality.ai, etc.). The library is designed to reduce common AI-style markers and normalize style, but external detectors use their own proprietary models and signals.

---

### 1. Install dependencies

From the `py-humanize` folder:

```bash
pip install -r requirements.txt
```

This installs:

- `texthumanize` ≥ 0.27.1
- `lxml` (used for safe DOCX XML edits)

---

### 2. Prepare your input file

Place your formatted research paper text in a plain UTF‑8 `.txt` file, for example:

- `whole.txt`

You can keep the editing site's template structure in this file; the script will humanize the content as raw text while preserving line breaks and most structural formatting.

---

### 3. Run the humanizer

Basic usage (from the `py-humanize` directory):

```bash
python humanize_paper.py whole.txt
```

This will:

- Read `whole.txt`
- Humanize it with `profile="academic"` and English language (`lang="en"`)
- Write the result to `whole.txt.humanized.txt` in the same directory

---

### 4. Advanced options

You can customize behavior via CLI flags:

```bash
python humanize_paper.py whole.txt \
  -o whole_academic_humanized.txt \
  --lang en \
  --profile academic \
  --intensity 30 \
  --seed 42 \
  --chunk-size 3000
```

- **`-o / --output`**: Custom output path.
- **`--lang`**: Language code (default: `en`).
- **`--profile`**: Processing profile (default: `academic`). Other options in `texthumanize` include `chat`, `web`, `seo`, `docs`, `formal`, `marketing`, `social`, `email`.
- **`--intensity`**: 0–100. If omitted, `texthumanize` uses the profile-specific default (for `academic`, ~25).
- **`--seed`**: Ensures deterministic output for the same input.
- **`--chunk-size`**: Approximate characters per chunk when splitting long documents internally.

---

### 5. Notes on AI detection

- `texthumanize` focuses on **style normalization** (sentence length, connectors, bureaucratic phrases, etc.).
- It can **reduce AI-style markers**, but the project itself explicitly states it **cannot guarantee** bypassing all third‑party AI detectors.
- For best results:
  - Start with `profile="academic"` and low–moderate `intensity` (20–40).
  - Manually review the humanized text to ensure scholarly tone, correct terminology, and no template artefacts were altered in an unintended way.

---

## DOCX Support (Word `.docx`)

This project also includes a DOCX-focused script: `humanize_docx.py`.

### What it edits

- Only the main body text inside `word/document.xml` by replacing the contents of `<w:t>` text nodes.
- It skips:
  - Word field instructions (`w:instrText`)
  - Word math nodes (`m:*`)

### Pitfalls / complications

- Word often splits visible text across multiple runs/text nodes, so humanizing per `<w:t>` can reduce global coherence.
- Formatting is preserved structurally (we do not change `w:rPr`, paragraph/run structure, etc.), but the wording changes are still inserted at the text-node level.

### Usage

```bash
python humanize_docx.py input.docx -o output.docx
```

Optional flags:

```bash
python humanize_docx.py input.docx -o output.docx \
  --lang en \
  --profile academic \
  --intensity 30 \
  --seed 42 \
  --min-chars 2
```

