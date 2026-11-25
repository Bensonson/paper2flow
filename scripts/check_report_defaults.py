#!/usr/bin/env python3
"""Exercise the bundled report defaults using an isolated synthetic second paper.

Requires the PDF reader used by the bridge (pypdf). Node is optional: use --node
PATH or put node on PATH for full generated-JavaScript DOM integration checks.
No Codex CLI, sign-in, model call, production report or browser is used. The
temporary loopback service and files are cleaned up. This is not visual QA.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import paper2flow as pw
import report_server as rs


class FakeRunner:
    def __init__(self):
        self.prompts: list[str] = []

    def run(self, prompt, directory, cancelled):
        self.prompts.append(prompt)
        return "Synthetic answer [page 1]"

    def stop(self):
        pass


def write_synthetic_pdf(path: Path) -> None:
    """Write a tiny original English PDF with stdlib only, then read it normally."""
    content = (b"BT /F1 12 Tf 50 790 Td "
               b"(Synthetic second-paper QA: parallel measurements merge into an analysis.) Tj "
               b"0 -20 Td (Read acoustic and lexical observations; merge outputs; compare findings.) Tj ET")
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
               b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    raw = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(raw))
        raw.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(raw)
    raw.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        raw.extend(f"{offset:010d} 00000 n \n".encode())
    raw.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    path.write_bytes(raw)


def make_fixture(root: Path) -> tuple[dict, dict]:
    pdf = root / "Synthetic Second Paper.pdf"
    write_synthetic_pdf(pdf)
    text, source, _ = pw.extract_source(pdf)
    assert "Synthetic second-paper QA" in text, "Synthetic PDF must have real extractable text"

    def node(sid, name, parents=()):
        evidence = [{"page": 1, "section": "Methods", "quote":
                     "Read acoustic and lexical observations; merge outputs; compare findings."}]
        return {"id": sid, "name": name, "task": f"English task for {name}.",
                "inputs": [f"English input for {name}"], "outputs": [f"English output for {name}"],
                "parameters": [{"name": "English parameter", "value": "English setting"}],
                "findings": f"English finding for {name}.", "algorithm": ["NamedAlgorithm"],
                "software": ["NamedSoftware"], "depends_on": list(parents), "evidence": evidence,
                "dependency_reasons": [{"step_id": parent, "basis": "explicit",
                                        "reason": f"English reason supplied by {parent}.",
                                        "evidence": copy.deepcopy(evidence)} for parent in parents]}

    en = {"schema_version": "1.0", "paper_title": "Synthetic Second Paper: English Original",
          "summary": "English summary authored directly from an English synthetic source.",
          "source": source, "notes": ["English caveat about the synthetic measurements."],
          "steps": [node("acoustic", "Read acoustic observations"),
                    node("lexical", "Read lexical observations"),
                    node("merge", "Merge independent observations", ("acoustic", "lexical")),
                    node("compare", "Compare the merged measurements", ("merge",))]}
    zh = copy.deepcopy(en)
    zh.update(paper_title="第二篇合成论文：中文译文", summary="从英文底稿翻译的中文概要。",
              notes=["合成测量的中文限制说明。"])
    for step in zh["steps"]:
        sid = step["id"]
        step.update(name="中文步骤 " + sid, task="中文任务 " + sid, inputs=["中文输入 " + sid],
                    outputs=["中文输出 " + sid], parameters=[{"name": "中文参数", "value": "中文设置"}],
                    findings="中文发现 " + sid)
        for reason in step["dependency_reasons"]:
            reason["reason"] = "中文先决原因 " + reason["step_id"]
    pw.render_report(en, root / "report.html", translations={"zh": zh})
    return en, zh


def check_http(root: Path, en: dict, zh: dict) -> dict:
    fake = FakeRunner()
    state = rs.ReportState(root, runner=fake)
    server = None
    worker = None
    occupied = socket.socket()
    try:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        occupied_port = occupied.getsockname()[1]
        server = rs.bind_report_server(state, occupied_port)
        assert server.server_address[1] != occupied_port
        assert not state._closed, "Port fallback must not close bridge state"
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(route, payload=None, auth=False, headers=None):
            values = dict(headers or {})
            if auth:
                values["Authorization"] = "Bearer " + state.token
            if payload is not None:
                values["Content-Type"] = "application/json"
            body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
            req = urllib.request.Request(server.origin + route, data=body, headers=values)
            try:
                with opener.open(req, timeout=5) as response:
                    return response.status, dict(response.headers), response.read()
            except urllib.error.HTTPError as error:
                return error.code, dict(error.headers), error.read()

        def ask(workflow, history=None):
            payload = {"workflow": workflow, "node_id": "merge", "question": "Why do these inputs merge?"}
            if history is not None:
                payload["history"] = history
            code, _, raw = request("/ask", payload, True)
            assert code == 202, f"Expected accepted fake question, got HTTP {code}"
            job = json.loads(raw)["job_id"]
            for _ in range(100):
                _, _, raw = request("/jobs/" + job, auth=True)
                result = json.loads(raw)
                if result["status"] != "running":
                    break
                time.sleep(.01)
            assert result["status"] == "completed", "Fake question did not complete"

        code, headers, raw = request("/report.html")
        assert code == 200 and headers["Cache-Control"] == "no-store"
        assert state.token.encode() in raw
        assert state.token not in (root / "report.html").read_text(encoding="utf-8")
        assert b"url.value=location.origin" in raw and b"connect.click()" in raw
        assert b"advanced.hidden=true" in raw
        code, _, raw = request("/report-status")
        status = json.loads(raw)
        assert code == 200 and status["service"] == rs.SERVICE and status["report_id"] == state.report_id
        assert state.token not in raw.decode()
        assert request("/health")[0] == 401
        assert request("/health", auth=True)[0] == 200
        for headers in [{"Origin": "https://foreign.example"},
                        {"Origin": "http://127.0.0.1:1234"},
                        {"Sec-Fetch-Site": "cross-site"}, {"Host": "foreign.example"}]:
            assert request("/report.html", headers=headers)[0] == 403
        ask(en)
        assert "English task" in fake.prompts[-1] and "Synthetic second-paper QA" in fake.prompts[-1]
        ask(zh, [{"question": "Prior English question", "answer": "Unsupported earlier claim"}])
        assert "中文任务" in fake.prompts[-1] and "Unsupported earlier claim" in fake.prompts[-1]
        assert "NEVER source evidence" in fake.prompts[-1]
        assert en["source"]["pdf_path"] in fake.prompts[-1].replace("\\\\", "\\")
        altered = copy.deepcopy(en)
        altered["steps"][2]["task"] = "Foreign workflow injected"
        assert request("/ask", {"workflow": altered, "node_id": "merge", "question": "x"}, True)[0] == 403
        assert request("/ask", {"workflow": en, "node_id": "merge", "question": "x",
                                "pdf": {"path": str(root / "wrong.pdf")}}, True)[0] == 403
        assert request("/ask", {"workflow": en, "node_id": "unknown", "question": "x"}, True)[0] == 400
        for history in [[{"question": "x", "answer": "y", "foreign": "z"}],
                        [{"question": "", "answer": "y"}]]:
            assert request("/ask", {"workflow": en, "node_id": "merge", "question": "x",
                                    "history": history}, True)[0] == 400
        for history in [[{"question": "x", "answer": "y"}] * 101,
                        [{"question": "x", "answer": "y" * 200001}]]:
            code, _, raw = request("/ask", {"workflow": en, "node_id": "merge", "question": "x",
                                            "history": history}, True)
            assert code == 413 and b"Nothing was truncated" in raw
        registry = rs._runtime_dir(root, "report.html") / "server.json"
        rs._atomic_json(registry, {"url": server.url, "report_id": state.report_id})
        saved = rs.subprocess.Popen
        def no_spawn(*args, **kwargs):
            raise AssertionError("Matching-service reuse must not launch another process")
        rs.subprocess.Popen = no_spawn
        try:
            assert rs.launch(root, open_browser=False) == server.url
        finally:
            rs.subprocess.Popen = saved
        assert rs._status(server.url, "wrong-report-id") is None
        assert state.token not in registry.read_text(encoding="utf-8")
        assert occupied.fileno() != -1
        assert len(fake.prompts) == 2, "Rejected requests must not reach even the fake runner"
        return {"passed": True, "kind": "temporary HTTP service with fake runner",
                "checks": ["automatic connection and token privacy", "Host/origin/authentication guards",
                           "original PDF and active-language question context", "explicit untrusted follow-up history",
                           "foreign workflow/PDF, malformed/oversized history rejection",
                           "verified launch reuse and safe occupied-port fallback"], "fake_calls": len(fake.prompts)}
    finally:
        if server is not None:
            if worker is not None:
                server.shutdown()
            server.server_close()
        else:
            state.close()
        if worker is not None:
            worker.join(3)
        occupied.close()


def check_translation(root, en, zh):
    for mutation in ("evidence", "depends", "source"):
        bad = copy.deepcopy(zh)
        if mutation == "evidence":
            bad["steps"][0]["evidence"][0]["quote"] = "Incorrectly translated source quote"
        elif mutation == "depends":
            bad["steps"][2]["depends_on"].reverse()
        else:
            bad["source"]["name"] = "different.pdf"
        try:
            pw.render_report(en, root / "bad.html", translations={"zh": bad})
        except pw.WorkflowError:
            pass
        else:
            raise AssertionError(f"Changed translation {mutation} was accepted")
    assert not (root / "bad.html").exists()
    pw.render_report(en, root / "english-only.html")
    assert "--launch" in (root / "OPEN_REPORT.cmd").read_text(encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", help="Node executable; auto-detected on PATH when omitted")
    args = parser.parse_args(argv)
    try:
        with tempfile.TemporaryDirectory(prefix="paper2flow-regression-") as temporary:
            root = Path(temporary)
            en, zh = make_fixture(root)
            check_translation(root, en, zh)
            results = [check_http(root, en, zh)]
            node = args.node or shutil.which("node")
            if node:
                companion = Path(__file__).with_suffix(".js")
                for report in ("report.html", "english-only.html"):
                    completed = subprocess.run([node, str(companion), str(root / report)],
                                               capture_output=True, text=True, timeout=30, shell=False)
                    if completed.returncode:
                        raise RuntimeError("Generated report JavaScript regression failed:\n" + completed.stderr.strip())
                    results.append(json.loads(completed.stdout.strip().splitlines()[-1]))
            else:
                results.append({"skipped": "Generated-JavaScript integration: Node unavailable; use --node PATH"})
            print(json.dumps({"passed": True, "results": results,
                              "limits": "Execution/HTTP checks only; no visual browser QA or scientific validation."},
                             ensure_ascii=True, indent=2))
        return 0
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
