#!/usr/bin/env python3
"""Training Library Stream - a dependency-free, local folder catalog."""

from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
PORT = int(os.environ.get("TRAINING_LIBRARY_PORT", "8794"))
# Tailscale Serve handles encrypted Tailnet traffic and proxies it here.
# Keeping the app on loopback avoids exposing the raw HTTP port to the LAN.
HOST = os.environ.get("TRAINING_LIBRARY_HOST", "127.0.0.1")
IGNORED = {".git", ".svn", "__pycache__", "node_modules", ".DS_Store"}
APP_ENTRIES = {"web", "app-data", "repository-packages", "server.py", "start-training-library.ps1", "install-startup-service.ps1", "README.md", ".gitignore"}
APP_DATA = ROOT / "app-data"
PROGRESS_FILE = APP_DATA / "watch-progress.json"
PROGRESS_LOCK = threading.Lock()


def iso_time(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_child(path: Path) -> bool:
    return path.name not in IGNORED and not path.name.startswith(".") and not path.is_symlink()


def scan_folder(path: Path, is_folder: bool | None = None) -> dict:
    """Return a JSON-friendly tree. Permission errors are represented safely."""
    try:
        is_folder = path.is_dir() if is_folder is None else is_folder
        node = {
            "name": path.name,
            "type": "folder" if is_folder else "file",
            "relativePath": str(path.relative_to(ROOT)).replace("\\", "/"),
        }
        if not is_folder:
            node["extension"] = path.suffix.lower().lstrip(".") or "other"
            return node
        children = []
        # scandir keeps type metadata with the directory listing. Avoiding a separate
        # stat call per file matters for a large OneDrive-backed training library.
        with os.scandir(path) as entries:
            visible = [entry for entry in entries if entry.name not in IGNORED and not entry.name.startswith(".") and not entry.is_symlink()]
        for entry in sorted(visible, key=lambda item: (not item.is_dir(), item.name.lower())):
            children.append(scan_folder(Path(entry.path), entry.is_dir()))
        node["children"] = children
        node["fileCount"] = sum(count_files(child) for child in children)
        return node
    except (OSError, PermissionError) as error:
        return {"name": path.name, "type": "unavailable", "relativePath": str(path.relative_to(ROOT)).replace("\\", "/"), "error": str(error)}


def count_files(node: dict) -> int:
    if node["type"] == "file":
        return 1
    return node.get("fileCount", 0)


def library_snapshot() -> dict:
    categories = []
    with os.scandir(ROOT) as entries:
        visible = [entry for entry in entries if entry.name not in IGNORED and entry.name not in APP_ENTRIES and not entry.name.startswith(".") and not entry.is_symlink()]
    for entry in sorted(visible, key=lambda item: item.name.lower()):
        categories.append(scan_folder(Path(entry.path), entry.is_dir()))
    files = sum(count_files(category) for category in categories)
    folders = sum(1 for category in categories if category["type"] == "folder")
    return {"generatedAt": iso_time(datetime.now().timestamp()), "root": ROOT.name, "summary": {"categories": folders, "files": files}, "categories": categories}


def watch_progress() -> dict:
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def update_watch_progress(relative_path: str, position: float, duration: float) -> None:
    with PROGRESS_LOCK:
        progress = watch_progress()
        progress[relative_path] = {
            "position": round(max(0, position), 1),
            "duration": round(max(0, duration), 1),
            "updatedAt": iso_time(datetime.now().timestamp()),
        }
        APP_DATA.mkdir(exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=APP_DATA, suffix=".tmp") as temporary:
            json.dump(progress, temporary, ensure_ascii=False, indent=2)
            temporary_path = Path(temporary.name)
        temporary_path.replace(PROGRESS_FILE)


class LibraryHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed = urlparse(path).path
        if parsed == "/":
            parsed = "/index.html"
        return str(WEB_ROOT / parsed.lstrip("/"))

    def do_GET(self) -> None:
        endpoint = urlparse(self.path).path
        if endpoint == "/api/library":
            self.send_json(library_snapshot())
        elif endpoint == "/api/progress":
            self.send_json(watch_progress())
        elif endpoint.startswith("/files/"):
            self.send_library_file(unquote(endpoint.removeprefix("/files/")))
        elif endpoint == "/events":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                # A snapshot is checked every five seconds. This avoids installing a watcher
                # and keeps the catalog current for every computer on the Tailnet.
                previous = ""
                while True:
                    current = json.dumps(library_snapshot(), sort_keys=True, ensure_ascii=False)
                    if current != previous:
                        self.wfile.write(b"event: library-change\\n")
                        self.wfile.write(b"data: refresh\\n\\n")
                        self.wfile.flush()
                        previous = current
                    import time
                    time.sleep(5)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            super().do_GET()

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/progress":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16_384:
                raise ValueError
            body = json.loads(self.rfile.read(length))
            relative_path = str(body["relativePath"])
            requested = (ROOT / relative_path).resolve()
            requested.relative_to(ROOT)
            if not requested.is_file() or requested.relative_to(ROOT).parts[0] in APP_ENTRIES:
                raise ValueError
            update_watch_progress(relative_path, float(body["position"]), float(body.get("duration", 0)))
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid progress update")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_headers()

    def do_HEAD(self) -> None:
        endpoint = urlparse(self.path).path
        if endpoint.startswith("/files/"):
            self.send_library_file(unquote(endpoint.removeprefix("/files/")), send_body=False)
        else:
            super().do_HEAD()

    def send_library_file(self, relative_path: str, send_body: bool = True) -> None:
        """Serve a catalogued file safely, including byte ranges for video seeking."""
        try:
            requested = (ROOT / relative_path).resolve()
            requested.relative_to(ROOT)
            if not requested.is_file() or requested.relative_to(ROOT).parts[0] in APP_ENTRIES:
                raise FileNotFoundError
        except (OSError, ValueError, FileNotFoundError):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return

        size = requested.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
            if not match:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            first, last = match.groups()
            if first:
                start = int(first)
                end = int(last) if last else end
            elif last:
                start = max(0, size - int(last))
            if start >= size or start > end:
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            end = min(end, size - 1)
            status = HTTPStatus.PARTIAL_CONTENT

        content_type = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{requested.name}")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if not send_body:
            return
        with requested.open("rb") as source:
            source.seek(start)
            remaining = length
            while remaining:
                chunk = source.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def send_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {self.address_string()} {fmt % args}")


if __name__ == "__main__":
    print(f"Training Library Stream is available at http://localhost:{PORT}")
    print(f"Scanning: {ROOT}")
    print("Use the Tailscale URL shown in README.md from other devices.")
    ThreadingHTTPServer((HOST, PORT), LibraryHandler).serve_forever()
