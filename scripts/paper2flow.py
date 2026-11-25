#!/usr/bin/env python3
"""Deterministic, offline source extraction and paper2flow utilities.

The host agent analyzes the paper and writes workflow JSON. These tools perform
no inference and make no network requests. Python 3.10+, optional pypdf for PDFs.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from dataclasses import dataclass
import hashlib
import html
import json
from pathlib import Path
import re
import shlex
import sys
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_ROOT / "references" / "workflow.schema.json"
TEMPLATE_PATH = SKILL_ROOT / "assets" / "report.html"


class WorkflowError(ValueError):
    """An actionable input, extraction or validation failure."""


@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]

    @property
    def valid(self) -> bool:
        return not self.errors


def read_json(path: str | Path) -> Any:
    def reject_constant(value: str) -> None:
        raise WorkflowError(f"Non-standard JSON constant: {value}")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise WorkflowError(f"Duplicate JSON object key: {key!r}")
            result[key] = value
        return result

    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                          parse_constant=reject_constant, object_pairs_hook=reject_duplicates)
    except json.JSONDecodeError as exc:
        raise WorkflowError(f"Invalid JSON in {path}: {exc}") from exc


def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _schema_errors(value: Any, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    """Validate the small JSON Schema vocabulary used by this bundled schema."""
    if "$ref" in schema:
        target = root
        for key in schema["$ref"][2:].split("/"):
            target = target[key]
        _schema_errors(value, target, root, path, errors)
        return
    types = schema.get("type", [])
    types = [types] if isinstance(types, str) else types
    matches = {
        "object": isinstance(value, dict), "array": isinstance(value, list),
        "string": isinstance(value, str), "integer": type(value) is int,
        "null": value is None,
    }
    if types and not any(matches.get(kind, False) for kind in types):
        errors.append(f"{path}: expected {' or '.join(types)}, got {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: expected one of {schema['enum']!r}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}.{key}: required field is missing")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                _schema_errors(item, props[key], root, f"{path}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key}: unknown field")
    elif isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: requires at least {schema['minItems']} item(s)")
        for index, item in enumerate(value):
            _schema_errors(item, schema.get("items", {}), root, f"{path}[{index}]", errors)
    elif isinstance(value, str):
        if len(value.strip()) < schema.get("minLength", 0):
            errors.append(f"{path}: must not be empty or whitespace")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            errors.append(f"{path}: does not match {schema['pattern']}")
    elif type(value) is int and "minimum" in schema and value < schema["minimum"]:
        errors.append(f"{path}: must be >= {schema['minimum']}")


def validate_workflow(data: Any) -> ValidationResult:
    schema = read_json(SCHEMA_PATH)
    errors: list[str] = []
    warnings: list[str] = []
    _schema_errors(data, schema, schema, "$", errors)
    if errors:
        return ValidationResult(errors, warnings)
    steps = data["steps"]
    identifiers = [step["id"] for step in steps]
    known = set(identifiers)
    for identifier, count in Counter(identifiers).items():
        if count > 1:
            errors.append(f"Duplicate step id: {identifier!r}")
    if not 4 <= len(steps) <= 10:
        warnings.append(f"Workflow has {len(steps)} steps; 4–10 is recommended when supported by the paper.")
    page_count = data["source"]["page_count"]
    if data["source"]["sha256"] is None:
        warnings.append("Source SHA-256 is absent; source identity has not been verified.")
    if not data["summary"].strip():
        warnings.append("Summary is empty.")

    def check_evidence(evidence: dict, path: str) -> None:
        page = evidence["page"]
        if page is not None and page_count is not None and page > page_count:
            errors.append(f"{path}.page: {page} exceeds source page_count {page_count}")
        if page is not None and page_count is None:
            warnings.append(f"{path}: page cannot be range-checked because source page_count is unknown.")
        if not evidence["quote"].strip():
            warnings.append(f"{path}: missing supporting quote; verify against source.")

    for step in steps:
        sid = step["id"]
        dependencies = step["depends_on"]
        for dependency, count in Counter(dependencies).items():
            if count > 1:
                errors.append(f"Step {sid!r}: duplicate dependency {dependency!r}")
            if dependency not in known:
                errors.append(f"Step {sid!r}: unknown dependency {dependency!r}")
            if dependency == sid:
                errors.append(f"Step {sid!r}: cannot depend on itself")
        reasons = Counter(reason["step_id"] for reason in step["dependency_reasons"])
        for dependency in set(dependencies):
            if reasons[dependency] != 1:
                errors.append(f"Step {sid!r}: dependency {dependency!r} requires exactly one dependency reason")
        for dependency in reasons:
            if dependency not in dependencies:
                errors.append(f"Step {sid!r}: reason for {dependency!r} has no matching depends_on entry")
        if not step["evidence"]:
            warnings.append(f"Step {sid!r}: no source evidence; verify this step against the paper.")
        for index, evidence in enumerate(step["evidence"]):
            check_evidence(evidence, f"Step {sid!r} evidence[{index}]")
        for index, reason in enumerate(step["dependency_reasons"]):
            if not reason["evidence"]:
                warnings.append(f"Step {sid!r} dependency_reasons[{index}]: no source evidence; verify the dependency.")
            for evidence_index, evidence in enumerate(reason["evidence"]):
                check_evidence(evidence, f"Step {sid!r} dependency_reasons[{index}].evidence[{evidence_index}]")
            if reason["basis"] == "inferred":
                warnings.append(f"Step {sid!r} ← {reason['step_id']!r}: dependency is inferred; review the justification.")
    if not errors:
        indegree = {step["id"]: len(step["depends_on"]) for step in steps}
        children: dict[str, list[str]] = {sid: [] for sid in known}
        for step in steps:
            for dependency in step["depends_on"]:
                children[dependency].append(step["id"])
        ready = deque(sid for sid, count in indegree.items() if count == 0)
        visited = 0
        while ready:
            sid = ready.popleft()
            visited += 1
            for child in children[sid]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(steps):
            cycle = [sid for sid, count in indegree.items() if count]
            errors.append(f"Dependency cycle detected (including downstream blocked steps): {', '.join(cycle)}")
    return ValidationResult(errors, warnings)


def require_valid(data: Any) -> ValidationResult:
    result = validate_workflow(data)
    if result.errors:
        raise WorkflowError("\n".join(result.errors))
    return result


def safe_json(data: Any) -> str:
    """Serialize for an HTML script element without allowing script termination."""
    result = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for char, escaped in (("&", "\\u0026"), ("<", "\\u003c"), (">", "\\u003e"),
                          ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        result = result.replace(char, escaped)
    return result


def require_equivalent_translation(primary: dict, translated: dict, language: str) -> ValidationResult:
    """Keep translation a textual view of the same evidence-linked workflow.

    Full canonical JSON is required: a UI-label dictionary is not a translation.
    Evidence is deliberately kept in its original language, without translation.
    """
    result = require_valid(translated)
    if translated["source"] != primary["source"]:
        raise WorkflowError(f"Translation {language!r}: source identity and original PDF binding must be unchanged")
    if [step["id"] for step in translated["steps"]] != [step["id"] for step in primary["steps"]]:
        raise WorkflowError(f"Translation {language!r}: step IDs and order must be unchanged")
    for original, localized in zip(primary["steps"], translated["steps"]):
        sid = original["id"]
        if localized["depends_on"] != original["depends_on"]:
            raise WorkflowError(f"Translation {language!r}, step {sid!r}: dependencies must be unchanged")
        if localized["evidence"] != original["evidence"]:
            raise WorkflowError(f"Translation {language!r}, step {sid!r}: original source evidence must be unchanged")
        original_reasons = original["dependency_reasons"]
        translated_reasons = localized["dependency_reasons"]
        if [(item["step_id"], item["basis"], item["evidence"]) for item in original_reasons] != [
                (item["step_id"], item["basis"], item["evidence"]) for item in translated_reasons]:
            raise WorkflowError(f"Translation {language!r}, step {sid!r}: dependency IDs, basis and evidence must be unchanged")
    return result


def write_report_launcher(out: Path) -> None:
    """Write a repeatable local launch entry; rendering never starts a service."""
    server = SKILL_ROOT / "scripts" / "report_server.py"
    arguments = [sys.executable, str(server.resolve()), str(out.parent.resolve()),
                 "--report", out.name, "--launch", "--open"]
    # Percent expansion is the only shell substitution in quoted CMD arguments.
    # Escape it; paths with embedded quotes/newlines cannot be represented safely.
    if any(any(char in value for char in ('"', '\r', '\n')) for value in arguments):
        raise WorkflowError("Launcher paths may not contain quotes or newlines")
    cmd = "@echo off\r\nchcp 65001 >nul\r\n" + " ".join('"' + value.replace('%', '%%') + '"' for value in arguments) + "\r\n"
    (out.parent / "OPEN_REPORT.cmd").write_bytes(cmd.encode("utf-8"))
    shell = "#!/bin/sh\nexec " + " ".join(shlex.quote(value) for value in arguments) + "\n"
    (out.parent / "OPEN_REPORT.sh").write_text(shell, encoding="utf-8")


def render_report(data: dict, out: str | Path, language: str = "en", template: str | Path | None = None,
                  translations: dict[str, dict] | None = None) -> ValidationResult:
    """Render English primary content plus optional complete canonical translations.

    The primary data is authored from the original paper in English; translations
    are derived from it. The return type and positional template argument retain
    compatibility with earlier callers.
    """
    result = require_valid(data)
    if language not in ("zh", "en"):
        raise WorkflowError("Report language must be zh or en")
    localized = {"en": data}
    for code, translated in (translations or {}).items():
        if code != "zh":
            raise WorkflowError("Translation language must be zh; English is the primary workflow")
        translated_result = require_equivalent_translation(data, translated, code)
        localized[code] = translated
        result.warnings.extend(f"Translation {code}: {warning}" for warning in translated_result.warnings)
    if language not in localized:
        raise WorkflowError(f"No full {language!r} content translation supplied; provide --translation {language}=PATH")
    template_path = Path(template) if template else TEMPLATE_PATH
    report = template_path.read_text(encoding="utf-8")
    markers = ("__WORKFLOW_DATA__", "__REPORT_LANGUAGE__", "__WORKFLOW_LOCALIZATIONS__")
    if any(report.count(marker) != 1 for marker in markers):
        raise WorkflowError("HTML template must contain each data/language/localizations placeholder exactly once")
    # One-pass replacement prevents marker-like source text from becoming template code.
    values = {"__WORKFLOW_DATA__": safe_json(data), "__REPORT_LANGUAGE__": safe_json(language),
              "__WORKFLOW_LOCALIZATIONS__": safe_json(localized)}
    report = re.sub("|".join(markers), lambda match: values[match.group()], report)
    report = re.sub(r'<html lang="[^"]*">', f'<html lang="{language}">', report, count=1)
    report = re.sub(r"<title>.*?</title>", lambda _: f"<title>{html.escape(localized[language]['paper_title'])}</title>",
                    report, count=1, flags=re.DOTALL | re.IGNORECASE)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    write_report_launcher(out)
    return result


def extract_source(path: str | Path) -> tuple[str, dict, list[str]]:
    path = Path(path)
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    warnings: list[str] = []
    metadata = {"name": path.name, "kind": "text", "page_count": None,
                "sha256": hashlib.sha256(raw).hexdigest()}
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise WorkflowError("PDF extraction requires optional pypdf: python -m pip install pypdf") from exc
        try:
            reader = PdfReader(path)
            if reader.is_encrypted and not reader.decrypt(""):
                raise WorkflowError("PDF is encrypted; provide a locally decrypted copy.")
            metadata.update(kind="pdf", page_count=len(reader.pages), pdf_path=str(path.resolve()))
            pages: list[str] = []
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                if not text.strip():
                    warnings.append(f"PDF page {index} has no extractable text; OCR may be required. No page was skipped.")
                pages.append(f"[page {index}]\n{text}")
            if not reader.pages:
                raise WorkflowError("PDF has no pages")
            if all(not page.split("\n", 1)[1].strip() for page in pages):
                warnings.append("All PDF pages are empty after extraction; run OCR locally before workflow analysis.")
            text = "\n\n".join(pages) + "\n"
        except WorkflowError:
            raise
        except Exception as exc:
            raise WorkflowError(f"Cannot extract PDF: {exc}") from exc
    elif suffix in (".txt", ".md", ".markdown"):
        try:
            decoded = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise WorkflowError("Text input must use UTF-8; convert encoding locally first.") from exc
        metadata["kind"] = "markdown" if suffix != ".txt" else "text"
        if not decoded.strip():
            warnings.append("Source text is empty; provide usable source material before workflow analysis.")
        text = "\n".join(f"[line {index}] {line}" for index, line in enumerate(decoded.splitlines(), 1)) + "\n"
    else:
        raise WorkflowError(f"Unsupported source extension {suffix!r}; use .pdf, .txt, .md or .markdown")
    return text, metadata, warnings


def write_extraction(path: str | Path, out: str | Path) -> tuple[str, dict, list[str]]:
    if Path(path).resolve() == Path(out).resolve():
        raise WorkflowError("Extraction output must differ from the source file; the original source was preserved")
    text, source, warnings = extract_source(path)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    write_json(str(out) + ".source.json", {"source": source, "source_path": str(Path(path).resolve()), "warnings": warnings})
    return text, source, warnings


def _legacy_unknown(data: dict, allowed: set[str], path: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise WorkflowError(f"{path}: unrecognized legacy fields {sorted(extra)!r}; resolve them explicitly before migration")


def migrate_legacy(data: Any, source_name: str = "legacy.json") -> dict:
    """Explicit migration, with review notes instead of invented source evidence."""
    if isinstance(data, dict) and "schema_version" in data:
        require_valid(data)
        return data
    if isinstance(data, list):
        data = {"paper_title": Path(source_name).stem, "steps": data}
    if not isinstance(data, dict):
        raise WorkflowError("Legacy workflow must be an object or a flat list of steps")
    _legacy_unknown(data, {"paper_title", "title", "summary", "source", "notes", "steps", "experiments", "stages"}, "$")
    if "paper_title" in data and "title" in data:
        raise WorkflowError("Legacy input contains both paper_title and title; resolve the ambiguity")
    title = data.get("paper_title", data.get("title", Path(source_name).stem))
    notes = data.get("notes", [])
    if not isinstance(notes, list) or any(not isinstance(note, str) for note in notes):
        raise WorkflowError("Legacy notes must be an array of strings")
    notes = list(notes)
    notes.append("Migrated legacy workflow. Dependency labels and missing evidence require source review; no page numbers were invented.")
    flattened: list[dict] = []

    def flatten(items: Any, path: str) -> None:
        if not isinstance(items, list):
            raise WorkflowError(f"{path}: expected an array")
        for index, item in enumerate(items):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                raise WorkflowError(f"{item_path}: expected an object")
            nested = [key for key in ("steps", "experiments", "stages") if key in item]
            if nested:
                if len(nested) != 1:
                    raise WorkflowError(f"{item_path}: ambiguous nested step collections")
                _legacy_unknown(item, {nested[0], "name", "title", "id", "description"}, item_path)
                labels = []
                for key in ("id", "name", "title", "description"):
                    if key in item:
                        if not isinstance(item[key], str) and not (key == "id" and type(item[key]) is int):
                            raise WorkflowError(f"{item_path}.{key}: expected a string")
                        labels.append(str(item[key]))
                if labels:
                    notes.append(f"Legacy grouping at {item_path}: {' / '.join(labels)}")
                flatten(item[nested[0]], f"{item_path}.{nested[0]}")
            else:
                flattened.append(item)

    collections = [key for key in ("steps", "experiments", "stages") if key in data]
    if len(collections) != 1:
        raise WorkflowError("Legacy input must have exactly one of steps, experiments or stages")
    flatten(data[collections[0]], f"$.{collections[0]}")
    steps = []
    step_fields = {"id", "name", "task", "description", "inputs", "outputs", "parameters", "param", "findings", "finding",
                   "algorithm", "software", "depends_on", "evidence", "dependency_reasons"}
    for index, old in enumerate(flattened):
        _legacy_unknown(old, step_fields, f"legacy step[{index}]")
        for required in ("id", "name"):
            if required not in old:
                raise WorkflowError(f"Legacy step[{index}].{required}: required field is missing")
        if "task" not in old and "description" not in old:
            raise WorkflowError(f"Legacy step[{index}].task: required field is missing (description is also accepted)")
        if "task" in old and "description" in old and old["task"] != old["description"]:
            raise WorkflowError(f"Legacy step[{index}]: task and description conflict; resolve the ambiguity")
        task = old.get("task", old.get("description"))
        if "parameters" in old and "param" in old:
            raise WorkflowError(f"Legacy step[{index}]: contains both parameters and param")
        if "findings" in old and "finding" in old:
            raise WorkflowError(f"Legacy step[{index}]: contains both findings and finding")
        sid = str(old["id"]) if type(old["id"]) is int else old["id"]
        params = old.get("parameters", old.get("param", []))
        if isinstance(params, dict):
            params = [{"name": key, "value": value} for key, value in params.items()]
        if not isinstance(params, list):
            raise WorkflowError(f"Legacy step {sid!r}: parameters must be an array or object")
        new_params = []
        for param in params:
            if not isinstance(param, dict) or set(param) != {"name", "value"}:
                raise WorkflowError(f"Legacy step {sid!r}: parameter entries require exactly name and value")
            value = param["value"]
            if isinstance(value, (dict, list)) or value is None:
                raise WorkflowError(f"Legacy step {sid!r}: parameter values must be strings or scalar numbers/booleans")
            new_params.append({"name": param["name"], "value": value if isinstance(value, str) else json.dumps(value, allow_nan=False)})
        dependencies = old.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise WorkflowError(f"Legacy step {sid!r}: depends_on must be an array")
        dependencies = [str(dep) if type(dep) is int else dep for dep in dependencies]
        findings = old.get("findings", old.get("finding"))
        if isinstance(findings, str) and findings.strip().casefold() in {"none", "null", "n/a"}:
            findings = None
        step = {"id": sid, "name": old["name"], "task": task, "parameters": new_params,
                "findings": findings, "depends_on": dependencies,
                "evidence": old.get("evidence", []),
                "dependency_reasons": old.get("dependency_reasons", [
                    {"step_id": dep, "basis": "inferred",
                     "reason": "Legacy dependency imported without source justification; verify against the paper.",
                     "evidence": []}
                    for dep in dependencies])}
        for field in ("inputs", "outputs", "algorithm", "software"):
            step[field] = old.get(field, [])
        steps.append(step)
    result = {"schema_version": "1.0", "paper_title": title, "summary": data.get("summary", ""),
              "source": data.get("source", {"name": source_name, "kind": "legacy", "page_count": None, "sha256": None}),
              "steps": steps, "notes": notes}
    require_valid(result)
    return result


def _print_result(result: ValidationResult) -> None:
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    extract = commands.add_parser("extract", help="Extract full source text locally; write .source.json sidecar")
    extract.add_argument("input", type=Path)
    extract.add_argument("--out", type=Path, required=True)
    validate = commands.add_parser("validate", help="Validate a v1.0 JSON workflow and its dependency DAG")
    validate.add_argument("input", type=Path)
    render = commands.add_parser("render", help="Render validated JSON as a self-contained offline HTML report")
    render.add_argument("input", type=Path)
    render.add_argument("--out", type=Path, required=True)
    render.add_argument("--language", choices=("zh", "en"), default="en")
    render.add_argument("--translation", action="append", default=[], metavar="zh=PATH",
                        help="Full canonical translation derived from the English primary workflow")
    migrate = commands.add_parser("migrate", help="Explicitly convert legacy steps/experiments/stages to v1.0")
    migrate.add_argument("input", type=Path)
    migrate.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "extract":
            _, _, warnings = write_extraction(args.input, args.out)
            _print_result(ValidationResult([], warnings))
            print(f"Extracted full source to {args.out}; metadata: {args.out}.source.json")
        elif args.command == "validate":
            result = validate_workflow(read_json(args.input))
            _print_result(result)
            print("VALID" if result.valid else "INVALID")
            return 0 if result.valid else 1
        elif args.command == "render":
            if args.input.resolve() == args.out.resolve():
                raise WorkflowError("HTML output must differ from the workflow JSON file; the original JSON was preserved")
            translations = {}
            for entry in args.translation:
                code, separator, path = entry.partition("=")
                if not separator or not path or code in translations:
                    raise WorkflowError("Each --translation must be a unique language=PATH mapping")
                translations[code] = read_json(path)
            result = render_report(read_json(args.input), args.out, args.language, translations=translations)
            _print_result(result)
            print(f"Rendered {args.out}")
        elif args.command == "migrate":
            data = migrate_legacy(read_json(args.input), args.input.name)
            write_json(args.out, data)
            _print_result(validate_workflow(data))
            print(f"Migrated {args.out}; review notes and inferred dependencies")
    except (WorkflowError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
