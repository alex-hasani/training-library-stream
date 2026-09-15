"""Private, dependency-free Training Navigator server."""
from __future__ import annotations
import ctypes, json, mimetypes, os, re, shutil, subprocess, threading
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
WEB_ROOT, DATA_ROOT = ROOT / "web", ROOT / "app-data"
PROGRESS_FILE = DATA_ROOT / "watch-progress.json"
COLLECTIONS_FILE = DATA_ROOT / "collections.json"
FFMPEG_CONFIG = DATA_ROOT / "ffmpeg-path.txt"
COLLECTIONS_LOCK = threading.Lock()
HOST, PORT = "127.0.0.1", 8794
HIDDEN_ROOTS = {(ROOT / "app-data").resolve(), (ROOT / "repository-packages").resolve()}
DRIVE_REMOVABLE, DRIVE_FIXED, HIDDEN_OR_SYSTEM = 2, 3, 0x2 | 0x4
VIDEO_TYPES = {".mkv": "video/x-matroska", ".avi": "video/x-msvideo", ".flv": "video/x-flv", ".wmv": "video/x-ms-wmv", ".mpeg": "video/mpeg", ".mpg": "video/mpeg", ".ts": "video/mp2t", ".m2ts": "video/mp2t", ".3gp": "video/3gpp"}

def browsable_drives():
    if os.name != "nt": return [Path("/")]
    mask, kernel32, drives = ctypes.windll.kernel32.GetLogicalDrives(), ctypes.windll.kernel32, []
    for index in range(26):
        if mask & (1 << index):
            drive = Path(f"{chr(65 + index)}:/")
            if kernel32.GetDriveTypeW(str(drive)) in (DRIVE_FIXED, DRIVE_REMOVABLE) and drive.exists(): drives.append(drive)
    return drives

def under(path, root):
    try: path.relative_to(root); return True
    except ValueError: return False

def allowed_path(raw, directory=None):
    if not raw: raise ValueError("A path is required.")
    path = Path(raw).expanduser().resolve()
    if not any(under(path, drive.resolve()) for drive in browsable_drives()): raise ValueError("Only mounted local drives can be browsed.")
    if any(path == hidden or under(path, hidden) for hidden in HIDDEN_ROOTS): raise ValueError("This application data folder is not browsable.")
    if not path.exists(): raise ValueError("This item is no longer available.")
    if directory is True and not path.is_dir(): raise ValueError("This path is not a folder.")
    if directory is False and not path.is_file(): raise ValueError("This path is not a file.")
    return path

def drive_payload(drive):
    free, total, available = ctypes.c_ulonglong(), ctypes.c_ulonglong(), ctypes.c_ulonglong()
    label = ctypes.create_unicode_buffer(261)
    try: ctypes.windll.kernel32.GetDiskFreeSpaceExW(str(drive), ctypes.byref(available), ctypes.byref(total), ctypes.byref(free))
    except OSError: pass
    try: ctypes.windll.kernel32.GetVolumeInformationW(str(drive), label, len(label), None, None, None, None, 0)
    except OSError: pass
    return {"name": drive.drive or str(drive), "label": label.value or "Local storage", "path": str(drive), "total": total.value, "free": free.value}

def entry_payload(entry):
    try:
        stat = entry.stat(follow_symlinks=False)
        if entry.name.startswith(".") or getattr(stat, "st_file_attributes", 0) & HIDDEN_OR_SYSTEM: return None
        path = Path(entry.path).resolve()
        if any(path == hidden or under(path, hidden) for hidden in HIDDEN_ROOTS): return None
        folder = entry.is_dir(follow_symlinks=False)
        return {"name": entry.name, "path": str(path), "kind": "folder" if folder else "file", "extension": "" if folder else path.suffix.lower().lstrip("."), "size": 0 if folder else stat.st_size, "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
    except OSError: return None

def browse(directory):
    try:
        with os.scandir(directory) as scanner: entries = [item for entry in scanner if (item := entry_payload(entry))]
    except PermissionError: raise ValueError("This folder cannot be read with the current Windows account.")
    parent = directory.parent if directory.parent != directory else None
    if parent and not any(under(parent, drive.resolve()) for drive in browsable_drives()): parent = None
    return {"path": str(directory), "parent": str(parent) if parent else None, "entries": entries, "refreshedAt": datetime.now(timezone.utc).isoformat()}

def load_progress():
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError): return {}

def save_progress(data):
    DATA_ROOT.mkdir(exist_ok=True); temporary = PROGRESS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"); temporary.replace(PROGRESS_FILE)

def load_collections():
    try:
        data = json.loads(COLLECTIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("favorites", []), list) and isinstance(data.get("playlists", []), list): return data
    except (OSError, json.JSONDecodeError): pass
    return {"favorites": [], "playlists": []}

def save_collections(data):
    DATA_ROOT.mkdir(exist_ok=True); temporary = COLLECTIONS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"); temporary.replace(COLLECTIONS_FILE)

def ffmpeg_path():
    try:
        configured = Path(FFMPEG_CONFIG.read_text(encoding="utf-8").strip())
        if configured.is_file(): return str(configured)
    except OSError: pass
    return shutil.which("ffmpeg")

def collection_view(data=None):
    data = data or load_collections()
    def describe(raw):
        try:
            path = allowed_path(raw, None); stat = path.stat(); folder = path.is_dir()
            return {"name": path.name or str(path), "path": str(path), "kind": "folder" if folder else "file", "extension": "" if folder else path.suffix.lower().lstrip("."), "size": 0 if folder else stat.st_size, "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()}
        except (OSError, ValueError): return None
    return {"favorites": [item for path in data["favorites"] if (item := describe(path)) and item["kind"] == "folder"], "playlists": [{"name": playlist.get("name", "Playlist"), "items": [item for path in playlist.get("items", []) if (item := describe(path)) and item["kind"] == "file"]} for playlist in data["playlists"]]}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(WEB_ROOT), **kwargs)
    def end_headers(self):
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff"); self.send_header("X-Frame-Options", "SAMEORIGIN"); super().end_headers()
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/drives": return self.send_json({"drives": [drive_payload(drive) for drive in browsable_drives()], "trainingPath": str(ROOT)})
        if parsed.path == "/api/browse": return self.handle_browse(parse_qs(parsed.query))
        if parsed.path == "/api/progress": return self.send_json(load_progress())
        if parsed.path == "/api/collections": return self.send_json(collection_view())
        if parsed.path == "/files": return self.serve_file(parse_qs(parsed.query), False)
        if parsed.path == "/transcode": return self.transcode_file(parse_qs(parsed.query))
        return super().do_GET()
    def do_HEAD(self):
        parsed = urlparse(self.path)
        if parsed.path == "/files": return self.serve_file(parse_qs(parsed.query), True)
        return super().do_HEAD()
    def do_POST(self):
        endpoint = urlparse(self.path).path
        try:
            payload = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
            if endpoint == "/api/progress":
                path = allowed_path(str(payload.get("path", ""))); position, duration = max(0, float(payload.get("position", 0))), max(0, float(payload.get("duration", 0)))
                data = load_progress(); data[str(path)] = {"position": position, "duration": duration, "updatedAt": datetime.now(timezone.utc).isoformat()}; save_progress(data); self.send_json({"ok": True})
            elif endpoint == "/api/favorites": self.update_favorite(payload)
            elif endpoint == "/api/playlists": self.update_playlist(payload)
            else: self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError, TypeError, json.JSONDecodeError) as error: self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def update_favorite(self, payload):
        path = str(allowed_path(str(payload.get("path", "")), True))
        with COLLECTIONS_LOCK:
            collections = load_collections()
            if bool(payload.get("favorite", True)):
                if path not in collections["favorites"]: collections["favorites"].append(path)
            elif path in collections["favorites"]: collections["favorites"].remove(path)
            save_collections(collections); response = collection_view(collections)
        self.send_json(response)

    def update_playlist(self, payload):
        action, name = str(payload.get("action", "create")), str(payload.get("name", "")).strip()
        def valid(value):
            if not value or len(value) > 80: raise ValueError("Playlist names must contain 1 to 80 characters.")
            return value
        with COLLECTIONS_LOCK:
            collections = load_collections()
            find = lambda value: next((item for item in collections["playlists"] if item.get("name", "").casefold() == value.casefold()), None)
            if action == "create":
                name = valid(name)
                if find(name): raise ValueError("A playlist with this name already exists.")
                collections["playlists"].append({"name": name, "items": []})
            elif action == "add":
                path = str(allowed_path(str(payload.get("path", "")), False)); names = payload.get("names", [])
                if not isinstance(names, list) or not names: raise ValueError("Select at least one playlist.")
                for selected in names:
                    playlist = find(valid(str(selected).strip()))
                    if not playlist: raise ValueError("One selected playlist no longer exists.")
                    if path not in playlist["items"]: playlist["items"].append(path)
            elif action == "rename":
                playlist, new_name = find(valid(str(payload.get("oldName", "")).strip())), valid(name)
                if not playlist: raise ValueError("Playlist not found.")
                if playlist["name"].casefold() != new_name.casefold() and find(new_name): raise ValueError("A playlist with this name already exists.")
                playlist["name"] = new_name
            elif action == "delete":
                playlist = find(valid(name))
                if not playlist: raise ValueError("Playlist not found.")
                collections["playlists"].remove(playlist)
            elif action == "remove-item":
                playlist = find(valid(name)); path = str(allowed_path(str(payload.get("path", "")), False))
                if not playlist: raise ValueError("Playlist not found.")
                if path in playlist["items"]: playlist["items"].remove(path)
            else: raise ValueError("Unknown playlist action.")
            save_collections(collections); response = collection_view(collections)
        self.send_json(response)
    def handle_browse(self, query):
        try: self.send_json(browse(allowed_path(unquote(query.get("path", [""])[0]), True)))
        except ValueError as error: self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8"); self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def transcode_file(self, query):
        try:
            path = allowed_path(unquote(query.get("path", [""])[0]), False); executable = ffmpeg_path()
            if not executable: raise ValueError("FFmpeg is not configured for this server.")
            command = [executable, "-hide_banner", "-loglevel", "error", "-i", str(path), "-map", "0:v:0?", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-movflags", "frag_keyframe+empty_moov", "-f", "mp4", "pipe:1"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
            first_chunk = process.stdout.read(64 * 1024)
            if not first_chunk:
                error_message = process.stderr.read().decode("utf-8", "replace").strip() or "FFmpeg could not convert this video."
                process.wait()
                raise ValueError(error_message[:500])
            self.send_response(HTTPStatus.OK); self.send_header("Content-Type", "video/mp4"); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(first_chunk)
            try:
                while chunk := process.stdout.read(64 * 1024): self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError): pass
            finally:
                if process.poll() is None: process.kill()
                process.wait()
        except (OSError, ValueError) as error: self.send_json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE)
    def serve_file(self, query, head_only):
        try:
            path = allowed_path(unquote(query.get("path", [""])[0])); size = path.stat().st_size; start, end, status = 0, max(0, size - 1), HTTPStatus.OK
            if range_header := self.headers.get("Range"):
                match = re.match(r"bytes=(\d*)-(\d*)$", range_header)
                if not match: raise ValueError("Invalid byte range.")
                left, right = match.groups()
                if left: start, end = int(left), int(right) if right else end
                elif right: start = max(0, size - int(right))
                if start > end or start >= size: self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE); return
                end, status = min(end, size - 1), HTTPStatus.PARTIAL_CONTENT
            self.send_response(status); self.send_header("Content-Type", VIDEO_TYPES.get(path.suffix.lower(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")); self.send_header("Content-Length", str(end - start + 1)); self.send_header("Accept-Ranges", "bytes")
            if status == HTTPStatus.PARTIAL_CONTENT: self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if not head_only:
                with path.open("rb") as source:
                    source.seek(start); remaining = end - start + 1
                    while remaining:
                        chunk = source.read(min(1024 * 1024, remaining))
                        if not chunk: break
                        self.wfile.write(chunk); remaining -= len(chunk)
        except (OSError, ValueError) as error: self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

if __name__ == "__main__":
    print(f"Training Navigator listening at http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
