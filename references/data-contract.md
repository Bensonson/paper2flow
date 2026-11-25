# Workflow data contract, version 1.0

The authoritative machine-readable shape is [workflow.schema.json](workflow.schema.json). The Python validator adds graph checks that JSON Schema alone cannot express.

## Top level

- `schema_version`: exactly `"1.0"`.
- `paper_title`, `summary`: strings; the summary briefly describes the study's objective and method.
- `source`: `name` (display filename), `kind` (`pdf`, `text`, `markdown`, `legacy`, or `demo`), `page_count` (positive integer or null), `sha256` (64 hexadecimal characters or null).
- PDF extraction also supplies `source.pdf_path`: the absolute original-PDF path, copied into new workflows so node questions attach the original automatically. It is optional for compatibility with older/non-PDF workflows; do not make users re-enter a recorded path.
- `steps`: at least one step. Array order is presentation order, not evidence of dependence.
- `notes`: strings describing coverage, ambiguity, or other material limitations.

## Each step

| Field | Shape and meaning |
| --- | --- |
| `id` | Nonempty unique string. Stable numeric strings or descriptive IDs both work. |
| `name`, `task` | Concrete action label and procedural explanation. |
| `inputs`, `outputs` | Arrays of strings; distinguish consumed resources from produced artifacts. |
| `parameters` | Array of `{ "name": "…", "value": "…" }`; preserve units. |
| `findings` | A string, or null for purely procedural steps. |
| `algorithm`, `software` | Arrays of explicitly reported names. |
| `depends_on` | Unique existing step IDs; no self references or cycles. |
| `evidence` | Array of source locators supporting the step. |
| `dependency_reasons` | Exactly one explanation per ID in `depends_on`. |

Each evidence object has `page` (positive physical PDF page number or null), `section` (string), and `quote` (string). For text, put line markers in `section` and leave `page` null. Never invent a locator.

Each dependency explanation has `step_id` (the prerequisite), `basis` (`explicit` or `inferred`), `reason` (concise explanation), and `evidence` (the same evidence array format). A root step has both dependency arrays empty.

## English primary and translations

`workflow.json` is the English account authored directly against the original paper by default. `workflow.zh.json` is its complete Chinese translation, also a canonical version 1.0 workflow. Render with `--translation zh=workflow.zh.json`; translations are bundled in the self-contained HTML, not inserted as non-schema fields into the canonical JSON.

Translations must preserve source metadata, stable IDs, dependency structure, basis labels, all source evidence/locators and original-language quotations. Translate explanatory names, tasks, inputs, outputs, parameter prose, findings, notes and dependency reasons without changing their meaning. The renderer validates structural/evidence identity; the author still checks scientific and numerical equivalence.

Language switching changes the full active workflow, including export, print and node-question context. English-only input must not expose a misleading label-only Chinese report. Interface localization is not evidence that the body has been translated.

## Reusing older data

Use the explicit `migrate` command for the former flat or nested schema. It normalizes `finding` to `findings` and parameter dictionaries to name/value arrays, and labels unverified imported dependencies as inferred. Read its notes: migration supplies structure, not missing scientific evidence. Invalid references or cycles still need source review.
