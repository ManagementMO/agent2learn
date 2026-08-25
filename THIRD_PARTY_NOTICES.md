# Third-party notices

Agent2Learn is licensed **Apache-2.0** (see [`LICENSE`](LICENSE)). This file records the licences of
the dependencies it declares.

**What this file is:** an attribution and compliance record for the stack tested at the version
below, read from the metadata of the actually-resolved distributions rather than from documentation.

**What this file is not:** legal advice, a claim that the built wheel vendors these dependencies, or
a claim that `uv.lock` governs what a later `pip install agent2learn` resolves. The wheel ships only
Agent2Learn's own code; dependencies are resolved and installed separately on the user's machine
under their own licences.

- **Baseline:** Agent2Learn 0.1.0
- **Verified:** 2026-08-25, from installed distribution metadata under Python 3.11
- **Refresh procedure:** after any dependency change run `uv lock`, then `uv sync --all-extras
  --group dev`, then re-read `importlib.metadata` for the direct dependencies below and update this
  table. CI fails the release if the generated notices differ from this file.

## Direct runtime dependencies

| Package | Version | Licence |
| --- | --- | --- |
| `typer` | 0.27.1 | MIT |
| `rich` | 14.3.4 | MIT |
| `requests` | 2.34.2 | Apache-2.0 |
| `platformdirs` | 4.11.4 | MIT |
| `keyring` | 25.7.0 | MIT |
| `websocket-client` | 1.9.0 | Apache-2.0 |
| **`pdf-oxide`** | **0.3.77 (exact-pinned)** | **MIT OR Apache-2.0** |
| `pytesseract` | 0.3.13 | Apache-2.0 |
| `pillow` | 12.3.0 | MIT-CMU |
| `pypdfium2` | 5.13.0 | Apache-2.0 OR BSD-3-Clause, plus bundled PDFium dependency licences |

## Optional extras

| Extra | Package | Version | Licence |
| --- | --- | --- | --- |
| `office` | `markitdown[pptx,docx,xlsx]` | 0.1.7 | MIT |
| `notebook` | `nbformat` | 5.11.1 | BSD-3-Clause |

Each extra pulls its own transitive dependencies. The complete resolved set — 122 packages at this
baseline — is recorded in [`uv.lock`](uv.lock), and a CycloneDX SBOM is produced during release.

## Notices requiring specific attention

### `pypdfium2` bundles PDFium

`pypdfium2` is an ABI-level binding to **PDFium**, which carries a BSD-style licence, and its wheels
bundle further dependency licences. Those notices ship inside the `pypdfium2` distribution and must
accompany any redistribution of it. Agent2Learn does not vendor `pypdfium2`; it is installed from
PyPI on the user's machine. Check the `BUILD_LICENSES/` directory of the installed distribution for
the exact set, which can change between builds.

### `pdf-oxide` is exact-pinned for a non-licensing reason

The pin exists because converter output is part of the citation contract and `pdf-oxide` has changed
extraction and Markdown artifact handling within a patch release. See `docs/FUTURE.md` and the
implementation plan's converter task.

### System Tesseract is an external prerequisite, not a bundled component

OCR uses `pytesseract`, which is a thin wrapper that shells out to a **Tesseract executable the user
installs themselves** (`winget install -e --id UB-Mannheim.TesseractOCR`, `brew install tesseract`,
`apt install tesseract-ocr`). Agent2Learn neither bundles nor redistributes Tesseract or its language
data, and never downloads OCR models. Tesseract is licensed Apache-2.0 by its own maintainers; its
notices are governed by however the user obtained it.

## Not a dependency

`pymupdf4llm` / PyMuPDF (AGPL-3.0 or Artifex commercial) was evaluated and **is not shipped or
supported** in v0.1. Agent2Learn declares no dependency on it and inherits no copyleft obligation
from it. The reasoning is recorded in the design spec and `docs/FUTURE.md`.
