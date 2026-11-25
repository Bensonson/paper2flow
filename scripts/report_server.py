#!/usr/bin/env python3
"""Serve an offline paper report and automatically connect its local Codex bridge.

Usage: report_server.py REPORT_DIRECTORY [--launch] [--open] [--port 0]
No model/key flags are set: the installed CLI reuses the user's own configuration.
The bearer token exists only in this process and in same-origin served HTML.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
from html.parser import HTMLParser
from http.server import ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import quote, unquote, urlsplit
import urllib.error
import urllib.request
import webbrowser

from agent_bridge import (BridgeError, BridgeHandler, BridgeServer, BridgeState,
                          _check_pdf_file, find_codex)
from paper2flow import require_valid, safe_json


SERVICE = "paper2flow-report"
REVISION = "english-first-followup-v1"
MAX_REPORT_BYTES = 16 * 1024 * 1024


class _EmbeddedJSON(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.values: dict[str, str] = {}
        self.current: str | None = None

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag.lower() == "script" and attributes.get("type") == "application/json":
            identifier = attributes.get("id")
            if identifier in {"workflow-data", "workflow-localizations"}:
                if identifier in self.values:
                    raise BridgeError("Rendered report contains duplicate workflow JSON blocks")
                self.current = identifier
                self.values[identifier] = ""

    def handle_data(self, data):
        if self.current is not None:
            self.values[self.current] += data

    def handle_endtag(self, tag):
        if tag.lower() == "script":
            self.current = None


def _read_report(path: Path) -> tuple[str, list[dict]]:
    if not path.is_file() or path.stat().st_size > MAX_REPORT_BYTES:
        raise BridgeError("Report must be a readable HTML file no larger than 16 MiB")
    html = path.read_text(encoding="utf-8")
    parser = _EmbeddedJSON()
    parser.feed(html)
    try:
        primary = json.loads(parser.values["workflow-data"])
        localized = json.loads(parser.values.get("workflow-localizations", "{}"))
    except (KeyError, TypeError, ValueError) as exc:
        raise BridgeError("Report does not contain valid embedded workflow JSON") from exc
    if not isinstance(localized, dict):
        raise BridgeError("Rendered report localizations must be a language-to-workflow object")
    workflows = [primary, *localized.values()]
    for workflow in workflows:
        require_valid(workflow)
    if not re.search(r"</body\s*>", html, re.IGNORECASE):
        raise BridgeError("Report is missing its closing body element")
    return html, workflows


def _check_authentication() -> None:
    executable = find_codex()
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    try:
        result = subprocess.run([str(executable), "login", "status"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=20, shell=False, **options)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BridgeError("Could not verify local Codex sign-in; open Codex and sign in, then reopen this report") from exc
    if result.returncode != 0:
        raise BridgeError("Local Codex is not signed in; open Codex and sign in, then reopen this report")


class ReportState(BridgeState):
    def __init__(self, report_dir: str | Path, report: str = "report.html", *,
                 workdir: str | Path | None = None, timeout: float = 300,
                 runner: Any = None, check_auth: bool = True):
        self.report_dir = Path(report_dir).resolve(strict=True)
        if not self.report_dir.is_dir() or Path(report).name != report or not report.endswith(".html"):
            raise BridgeError("Choose an existing report directory and an HTML report basename")
        self.report_name = report
        self.report_id = hashlib.sha256(str(self.report_dir / report).encode("utf-8")).hexdigest()
        self.source: dict | None = None
        self.workflows: list[dict] = []
        self.pages: dict[str, str] = {}
        self.load_reports()
        if runner is None and check_auth:
            _check_authentication()
        super().__init__("codex", workdir or self.report_dir, timeout=timeout, runner=runner)

    def load_reports(self) -> None:
        """Trust only the canonical workflows actually embedded in rendered pages."""
        name = Path(self.report_name)
        pattern = re.compile(re.escape(name.stem) + r"(?:\.[a-z]{2,3}(?:-[a-z0-9]+)?)?\.html$", re.I)
        paths = [self.report_dir / self.report_name]
        paths.extend(path for path in self.report_dir.glob(name.stem + ".*.html")
                     if pattern.fullmatch(path.name) and path not in paths)
        pages, workflows = {}, []
        for path in paths:
            if path.resolve().parent != self.report_dir:
                raise BridgeError("Report pages must stay inside their report directory")
            html, variants = _read_report(path)
            pages["/" + path.name] = html
            workflows.extend(variants)
        source = workflows[0]["source"]
        if (source.get("kind") != "pdf" or not source.get("pdf_path")
                or not source.get("sha256") or not Path(source["pdf_path"]).is_absolute()):
            raise BridgeError("The report must bind its original PDF absolute path and SHA-256 before automatic questions")
        if any(workflow["source"] != source for workflow in workflows):
            raise BridgeError("All rendered language variants must bind the same original PDF")
        if self.source is not None and self.source != source:
            raise BridgeError("The report's original PDF binding changed; restart this report service", 409)
        _, digest = _check_pdf_file(Path(source["pdf_path"]))
        if digest != source["sha256"]:
            raise BridgeError("The original PDF does not match the report's SHA-256")
        self.source, self.workflows, self.pages = source, workflows, pages

    def submit(self, payload: Any) -> str:
        self.load_reports()
        if not isinstance(payload, dict) or payload.get("workflow") not in self.workflows:
            raise BridgeError("Reload the current report before asking about a node", 403)
        pdf = payload.get("pdf")
        if pdf is not None and pdf != {"path": self.source["pdf_path"]}:
            raise BridgeError("This report uses its bound original PDF automatically", 403)
        return super().submit(payload)

    def page(self, path: str) -> bytes:
        self.load_reports()
        if path == "/":
            path = "/" + self.report_name
        if path not in self.pages:
            raise BridgeError("Unknown report page", 404)
        # A private runtime response, never a saved HTML file or log item.
        bootstrap = r"""
<script>
(()=>{
 const url=document.getElementById('agent-url'),token=document.getElementById('agent-token'),
 connect=document.getElementById('agent-connect'),status=document.getElementById('agent-connection-status');
 if(!url||!token||!connect||!status)return;
 const advanced=url.closest('details');if(advanced){advanced.insertAdjacentElement('afterend',status);advanced.hidden=true;}
 const chip=document.createElement('button');chip.type='button';chip.className='button';
 const labels={en:{connecting:'Connecting to local Codex',connected:'Local Codex connected · Ask about a step',retry:'Retry local Codex connection',ready:'Connected automatically. Select a step and ask a question.'},zh:{connecting:'正在连接本机 Codex',connected:'本机 Codex 已连接 · 追问当前步骤',retry:'重试连接本机 Codex',ready:'已自动连接。选中步骤即可提问。'}};
 const update=()=>{const copy=labels[document.documentElement.lang==='zh'?'zh':'en'],state=status.dataset.state;
 chip.textContent=state==='connected'?copy.connected:state==='error'?copy.retry:copy.connecting;
 if(state==='connected'&&status.textContent!==copy.ready)status.textContent=copy.ready;};
 chip.addEventListener('click',()=>{const opener=document.getElementById('agent-open');if(opener)opener.click();if(status.dataset.state==='error')connect.click();});
 const utilities=document.getElementById('utilities');if(utilities)utilities.prepend(chip);
 let previous='';new MutationObserver(()=>{if(previous!==status.dataset.state){previous=status.dataset.state;update();}}).observe(status,{attributes:true,childList:true,subtree:true});
 new MutationObserver(update).observe(document.documentElement,{attributes:true,attributeFilter:['lang']});
 url.value=location.origin;token.value=__RUNTIME_TOKEN__;
 url.dispatchEvent(new Event('input',{bubbles:true}));token.dispatchEvent(new Event('input',{bubbles:true}));update();connect.click();
})();
</script>
""".replace("__RUNTIME_TOKEN__", safe_json(self.token))
        return re.sub(r"</body\s*>", lambda match: bootstrap + match.group(), self.pages[path],
                      count=1, flags=re.IGNORECASE).encode("utf-8")


class ReportHandler(BridgeHandler):
    server_version = "paper2flowReport/1.0"

    def report_guard(self) -> None:
        self._guard(authenticate=False)
        origin = self.headers.get("Origin")
        if origin is not None and origin != self.server.origin:
            raise BridgeError("Automatic connection is available only from this same-origin local report", 403)
        if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
            raise BridgeError("Open the local report directly", 403)

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path != "/report-status" and path != "/" and path not in self.state.pages:
            return super().do_GET()
        try:
            self.report_guard()
            if path == "/report-status":
                self._reply(200, {"service": SERVICE, "report_id": self.state.report_id,
                                  "revision": REVISION, "agent": "codex", "ready": True,
                                  "busy": self.state._busy, "url": self.server.url})
                return
            raw = self.state.page(path)
            self.send_response(200)
            for key, value in (("Content-Type", "text/html; charset=utf-8"),
                               ("Content-Length", str(len(raw))), ("Cache-Control", "no-store"),
                               ("Referrer-Policy", "no-referrer"), ("X-Content-Type-Options", "nosniff"),
                               ("X-Frame-Options", "DENY"), ("Cross-Origin-Resource-Policy", "same-origin")):
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(raw)
        except (BridgeError, OSError, ValueError) as exc:
            self._reply(getattr(exc, "status", 409), {"error": self.state.redact(str(exc))})


class ReportServer(BridgeServer):
    def __init__(self, address: tuple[str, int], state: ReportState):
        # TCPServer closes its socket after bind failure. Keep the shared state alive
        # so an occupied preferred port can fall back to a fresh automatic port.
        self._bound = False
        super().__init__(address, state)
        self._bound = True
        self.RequestHandlerClass = ReportHandler
        self.origin = f"http://127.0.0.1:{self.server_address[1]}"
        self.url = self.origin + "/" + quote(state.report_name)

    def server_close(self) -> None:
        if self._bound:
            super().server_close()
        else:
            ThreadingHTTPServer.server_close(self)


def bind_report_server(state: ReportState, port: int = 0) -> ReportServer:
    if not 0 <= port <= 65535:
        raise BridgeError("Port must be between 0 (automatic) and 65535")
    try:
        return ReportServer(("127.0.0.1", port), state)
    except OSError as exc:
        # Windows exclusive listeners/reserved ports can report WSAEACCES rather
        # than WSAEADDRINUSE. Choosing another local port never modifies them.
        if port and (exc.errno in {errno.EADDRINUSE, errno.EACCES}
                     or getattr(exc, "winerror", None) in {10048, 10013}):
            return ReportServer(("127.0.0.1", 0), state)
        raise


def _runtime_dir(report_dir: Path, report: str) -> Path:
    key = hashlib.sha256(str(report_dir / report).encode("utf-8")).hexdigest()[:16]
    directory = report_dir / ".paper2flow-runtime" / key
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _status(url: str, report_id: str) -> dict | None:
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.port:
            return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        origin = f"http://127.0.0.1:{parsed.port}"
        with opener.open(origin + "/report-status", timeout=1) as response:
            value = json.load(response)
        if (value.get("service") == SERVICE and value.get("report_id") == report_id
                and value.get("revision") == REVISION and value.get("ready") is True
                and value.get("url") == url):
            # Verify the report itself before returning or opening a browser.
            with opener.open(url, timeout=2) as response:
                if response.status != 200 or response.headers.get_content_type() != "text/html":
                    return None
            return value
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return None


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def launch(report_dir: Path, report: str = "report.html", *, port: int = 0,
           timeout: float = 300, workdir: Path | None = None, open_browser: bool = False) -> str:
    """Reuse a verified matching service; never stop or commandeer an occupied port."""
    report_dir = report_dir.resolve(strict=True)
    if not report_dir.is_dir() or Path(report).name != report or not report.endswith(".html"):
        raise BridgeError("Choose an existing report directory and an HTML report basename")
    if not 0 <= port <= 65535 or not math.isfinite(timeout) or not 1 <= timeout <= 3600:
        raise BridgeError("Choose port 0–65535 and a timeout between 1 and 3600 seconds")
    report_id = hashlib.sha256(str(report_dir / report).encode("utf-8")).hexdigest()
    runtime = _runtime_dir(report_dir, report)
    registry = runtime / "server.json"
    lock = runtime / "launch.lock"
    deadline = time.monotonic() + 30
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise BridgeError("Another report launch is still starting; retry shortly")
            # A stale launch lock is not a running service; reclaim only after five minutes.
            if time.time() - lock.stat().st_mtime > 300:
                lock.unlink(missing_ok=True)
            time.sleep(0.1)
    try:
        try:
            previous = json.loads(registry.read_text(encoding="utf-8"))
            url = previous.get("url", "")
            if isinstance(url, str) and _status(url, report_id):
                if open_browser:
                    webbrowser.open(url)
                return url
        except (OSError, ValueError, AttributeError):
            pass
        command = [sys.executable, "-u", str(Path(__file__).resolve()), str(report_dir),
                   "--report", report, "--port", str(port), "--timeout", str(timeout)]
        if workdir is not None:
            command += ["--workdir", str(workdir.resolve())]
        options = ({"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS}
                   if os.name == "nt" else {"start_new_session": True})
        with (runtime / "server.log").open("ab") as log:
            process = subprocess.Popen(command, cwd=report_dir, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=log, shell=False, **options)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                current = json.loads(registry.read_text(encoding="utf-8"))
                url = current.get("url", "")
                if isinstance(url, str) and _status(url, report_id):
                    if open_browser:
                        webbrowser.open(url)
                    return url
            except (OSError, ValueError, AttributeError):
                pass
            if process.poll() is not None:
                break
            time.sleep(0.15)
        raise BridgeError(f"Local report did not start; inspect {runtime / 'server.log'}. The saved HTML remains available offline")
    finally:
        lock.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--report", default="report.html")
    parser.add_argument("--launch", action="store_true", help="Reuse or start a hidden background report service")
    parser.add_argument("--open", action="store_true", help="Open a browser after verifying HTTP readiness")
    parser.add_argument("--port", type=int, default=0, help="Preferred port; 0 chooses an available port automatically")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args(argv)
    state = server = None
    try:
        if Path(args.report).name != args.report or not args.report.endswith(".html"):
            raise BridgeError("Report must be an HTML basename inside the report directory")
        if not 0 <= args.port <= 65535:
            raise BridgeError("Port must be between 0 and 65535")
        if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 3600:
            raise BridgeError("Timeout must be between 1 and 3600 seconds")
        if args.launch:
            print(launch(args.report_dir, args.report, port=args.port, timeout=args.timeout,
                         workdir=args.workdir, open_browser=args.open), flush=True)
            return 0
        state = ReportState(args.report_dir, args.report, timeout=args.timeout, workdir=args.workdir)
        server = bind_report_server(state, args.port)
        runtime = _runtime_dir(state.report_dir, state.report_name)
        _atomic_json(runtime / "server.json", {"url": server.url, "pid": os.getpid(),
                                               "report_id": state.report_id, "revision": REVISION})
        print(server.url, flush=True)
        # Readiness is checked by a separate thread while serve_forever begins accepting.
        if args.open:
            def open_when_ready():
                if _status(server.url, state.report_id):
                    webbrowser.open(server.url)
            threading.Thread(target=open_when_ready, daemon=True).start()
        if threading.current_thread() is threading.main_thread():
            def stop(signum, frame):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, stop)
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print("ERROR: " + (state.redact(str(exc)) if state else str(exc)), file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.server_close()
        elif state is not None:
            state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
