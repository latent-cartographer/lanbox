#!/usr/bin/env python3
import cgi
import json
import mimetypes
import os
import posixpath
import re
import shutil
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from html import escape
from http import HTTPStatus
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
ITEMS_FILE = DATA_DIR / "items.json"
MAX_UPLOAD_MB = int(os.environ.get("LANBOX_MAX_UPLOAD_MB", "1024"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
CLIENT_TTL_SECONDS = int(os.environ.get("LANBOX_CLIENT_TTL_SECONDS", "20"))
BACKGROUND_CLIENT_TTL_SECONDS = int(os.environ.get("LANBOX_BACKGROUND_CLIENT_TTL_SECONDS", "600"))
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("LANBOX_CLEANUP_INTERVAL_SECONDS", "5"))

ITEM_LOCK = threading.Lock()
ACTIVE_LOCK = threading.Lock()
ACTIVE_CLIENTS = {}

QR_VERSION = 4
QR_SIZE = 17 + 4 * QR_VERSION
QR_DATA_CODEWORDS = 80
QR_ECC_CODEWORDS = 20


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs():
    PUBLIC_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    if not ITEMS_FILE.exists():
        ITEMS_FILE.write_text("[]\n", encoding="utf-8")


def load_items():
    ensure_dirs()
    try:
        return json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        backup = ITEMS_FILE.with_suffix(f".broken-{int(time.time())}.json")
        ITEMS_FILE.rename(backup)
        ITEMS_FILE.write_text("[]\n", encoding="utf-8")
        return []


def save_items(items):
    tmp = ITEMS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(ITEMS_FILE)


def safe_filename(name):
    name = Path(name or "file").name
    name = re.sub(r"[\x00-\x1f/\\:]+", "_", name).strip(" .")
    return name or "file"


def unique_path(folder, filename):
    base = safe_filename(filename)
    stem = Path(base).stem or "file"
    suffix = Path(base).suffix
    candidate = folder / base
    index = 2
    while candidate.exists():
        candidate = folder / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


def form_file_fields(form, name):
    if name not in form:
        return []
    field = form[name]
    return field if isinstance(field, list) else [field]


def prune_active_clients():
    now = time.time()
    expired = []
    for client_id, client in ACTIVE_CLIENTS.items():
        if isinstance(client, dict):
            seen_at = float(client.get("seen_at", 0))
            state = client.get("state", "active")
        else:
            seen_at = float(client)
            state = "active"
        ttl = BACKGROUND_CLIENT_TTL_SECONDS if state == "background" else CLIENT_TTL_SECONDS
        if seen_at < now - ttl:
            expired.append(client_id)
    for client_id in expired:
        ACTIVE_CLIENTS.pop(client_id, None)


def active_client_counts():
    counts = {"active": 0, "background": 0}
    for client in ACTIVE_CLIENTS.values():
        state = client.get("state", "active") if isinstance(client, dict) else "active"
        if state not in counts:
            state = "active"
        counts[state] += 1
    return counts


def remove_unsaved_items_if_idle():
    with ACTIVE_LOCK:
        prune_active_clients()
        if ACTIVE_CLIENTS:
            return 0

    removed_ids = []
    with ITEM_LOCK:
        items = load_items()
        kept = []
        for item in items:
            if item.get("saved"):
                kept.append(item)
            else:
                removed_ids.append(item.get("id"))
        if removed_ids:
            save_items(kept)

    for item_id in removed_ids:
        if item_id:
            shutil.rmtree(UPLOAD_DIR / item_id, ignore_errors=True)
    return len(removed_ids)


def cleanup_loop():
    while True:
        time.sleep(CLEANUP_INTERVAL_SECONDS)
        try:
            remove_unsaved_items_if_idle()
        except Exception as exc:
            sys.stderr.write(f"cleanup error: {exc}\n")


def local_addresses(port):
    addresses = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    return [f"http://{ip}:{port}" for ip in addresses]


def json_bytes(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def gf_mul(left, right):
    value = 0
    while right:
        if right & 1:
            value ^= left
        left <<= 1
        if left & 0x100:
            left ^= 0x11D
        right >>= 1
    return value


def rs_generator(degree):
    poly = [1]
    root = 1
    for _ in range(degree):
        next_poly = [0] * (len(poly) + 1)
        for index, coeff in enumerate(poly):
            next_poly[index] ^= coeff
            next_poly[index + 1] ^= gf_mul(coeff, root)
        poly = next_poly
        root = gf_mul(root, 2)
    return poly


def rs_ecc(data, degree):
    generator = rs_generator(degree)
    result = [0] * degree
    for value in data:
        factor = value ^ result.pop(0)
        result.append(0)
        for index, coeff in enumerate(generator[1:]):
            result[index] ^= gf_mul(coeff, factor)
    return result


def qr_payload_codewords(text):
    raw = text.encode("utf-8")
    bits = "0100" + f"{len(raw):08b}" + "".join(f"{byte:08b}" for byte in raw)
    capacity_bits = QR_DATA_CODEWORDS * 8
    if len(bits) > capacity_bits:
        raise ValueError("QR payload too long")
    bits += "0" * min(4, capacity_bits - len(bits))
    bits += "0" * ((8 - len(bits) % 8) % 8)
    codewords = [int(bits[index:index + 8], 2) for index in range(0, len(bits), 8)]
    if len(codewords) < QR_DATA_CODEWORDS:
        codewords.append(0)
    pads = [0xEC, 0x11]
    pad_index = 0
    while len(codewords) < QR_DATA_CODEWORDS:
        codewords.append(pads[pad_index % 2])
        pad_index += 1
    return codewords


def draw_finder(matrix, reserved, row, col):
    for dy in range(-1, 8):
        for dx in range(-1, 8):
            y = row + dy
            x = col + dx
            if not (0 <= y < QR_SIZE and 0 <= x < QR_SIZE):
                continue
            reserved[y][x] = True
            if 0 <= dy <= 6 and 0 <= dx <= 6:
                matrix[y][x] = dy in (0, 6) or dx in (0, 6) or (2 <= dy <= 4 and 2 <= dx <= 4)
            else:
                matrix[y][x] = False


def draw_alignment(matrix, reserved, center_row, center_col):
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            y = center_row + dy
            x = center_col + dx
            reserved[y][x] = True
            matrix[y][x] = max(abs(dx), abs(dy)) != 1


def qr_base_matrix():
    matrix = [[False] * QR_SIZE for _ in range(QR_SIZE)]
    reserved = [[False] * QR_SIZE for _ in range(QR_SIZE)]
    draw_finder(matrix, reserved, 0, 0)
    draw_finder(matrix, reserved, 0, QR_SIZE - 7)
    draw_finder(matrix, reserved, QR_SIZE - 7, 0)
    draw_alignment(matrix, reserved, 26, 26)
    for index in range(8, QR_SIZE - 8):
        value = index % 2 == 0
        matrix[6][index] = value
        matrix[index][6] = value
        reserved[6][index] = True
        reserved[index][6] = True
    for index in range(8):
        reserved[8][index] = True
        reserved[index][8] = True
        reserved[8][QR_SIZE - 1 - index] = True
        reserved[QR_SIZE - 1 - index][8] = True
    reserved[8][8] = True
    matrix[4 * QR_VERSION + 9][8] = True
    reserved[4 * QR_VERSION + 9][8] = True
    return matrix, reserved


def qr_mask(mask, row, col):
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def place_qr_data(matrix, reserved, codewords, mask):
    bits = "".join(f"{codeword:08b}" for codeword in codewords)
    bit_index = 0
    upward = True
    col = QR_SIZE - 1
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(QR_SIZE - 1, -1, -1) if upward else range(QR_SIZE)
        for row in rows:
            for current_col in (col, col - 1):
                if reserved[row][current_col]:
                    continue
                value = bit_index < len(bits) and bits[bit_index] == "1"
                bit_index += 1
                if qr_mask(mask, row, current_col):
                    value = not value
                matrix[row][current_col] = value
        upward = not upward
        col -= 2


def format_bits(mask):
    value = (1 << 3) | mask
    data = value << 10
    generator = 0x537
    for bit in range(14, 9, -1):
        if data & (1 << bit):
            data ^= generator << (bit - 10)
    return ((value << 10) | data) ^ 0x5412


def place_format_bits(matrix, mask):
    bits = f"{format_bits(mask):015b}"
    first = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
             (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    second = [(QR_SIZE - 1, 8), (QR_SIZE - 2, 8), (QR_SIZE - 3, 8), (QR_SIZE - 4, 8),
              (QR_SIZE - 5, 8), (QR_SIZE - 6, 8), (QR_SIZE - 7, 8), (8, QR_SIZE - 8),
              (8, QR_SIZE - 7), (8, QR_SIZE - 6), (8, QR_SIZE - 5), (8, QR_SIZE - 4),
              (8, QR_SIZE - 3), (8, QR_SIZE - 2), (8, QR_SIZE - 1)]
    for index, (row, col) in enumerate(first):
        matrix[row][col] = bits[index] == "1"
    for index, (row, col) in enumerate(second):
        matrix[row][col] = bits[index] == "1"


def penalty(matrix):
    score = 0
    for rows in (matrix, list(zip(*matrix))):
        for row in rows:
            run_color = row[0]
            run_len = 1
            for value in row[1:]:
                if value == run_color:
                    run_len += 1
                else:
                    if run_len >= 5:
                        score += 3 + run_len - 5
                    run_color = value
                    run_len = 1
            if run_len >= 5:
                score += 3 + run_len - 5
    for row in range(QR_SIZE - 1):
        for col in range(QR_SIZE - 1):
            block = matrix[row][col] + matrix[row + 1][col] + matrix[row][col + 1] + matrix[row + 1][col + 1]
            if block in (0, 4):
                score += 3
    dark = sum(sum(row) for row in matrix)
    total = QR_SIZE * QR_SIZE
    score += abs(dark * 20 - total * 10) // total * 10
    return score


def make_qr_matrix(text):
    data = qr_payload_codewords(text)
    codewords = data + rs_ecc(data, QR_ECC_CODEWORDS)
    best_matrix = None
    best_score = None
    for mask in range(8):
        matrix, reserved = qr_base_matrix()
        place_qr_data(matrix, reserved, codewords, mask)
        place_format_bits(matrix, mask)
        score = penalty(matrix)
        if best_score is None or score < best_score:
            best_matrix = matrix
            best_score = score
    return best_matrix


def terminal_qr(text):
    matrix = make_qr_matrix(text)
    quiet = 2
    white = "  "
    black = "██"
    lines = []
    width = QR_SIZE + quiet * 2
    lines.extend([white * width] * quiet)
    for row in matrix:
        lines.append(white * quiet + "".join(black if value else white for value in row) + white * quiet)
    lines.extend([white * width] * quiet)
    return "\n".join(lines)


def qr_svg(text, scale=8, border=4):
    matrix = make_qr_matrix(text)
    size = QR_SIZE + border * 2
    rects = []
    for row, values in enumerate(matrix):
        for col, value in enumerate(values):
            if value:
                rects.append(f"M{col + border},{row + border}h1v1h-1z")
    path = "".join(rects)
    title = escape(text, quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size * scale}" height="{size * scale}" shape-rendering="crispEdges" role="img">'
        f"<title>{title}</title>"
        f'<rect width="100%" height="100%" fill="#fff"/>'
        f'<path d="{path}" fill="#111"/>'
        "</svg>"
    )


def print_access_info(port):
    local_url = f"http://127.0.0.1:{port}"
    addresses = local_addresses(port)
    print(f"LanBox running on {local_url}")
    for address in addresses:
        print(f"LAN address: {address}")
    if os.environ.get("LANBOX_TERMINAL_QR") == "1" and addresses:
        print("\nScan to open on another device:")
        try:
            print(terminal_qr(addresses[0]))
        except ValueError:
            print(f"QR skipped: address is too long ({addresses[0]})")
    print(f"Data directory: {DATA_DIR}")
    print("Press Ctrl+C to stop.")


class LanBoxHandler(BaseHTTPRequestHandler):
    server_version = "LanBox/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - - [%s] %s\n" % (
            self.client_address[0],
            self.log_date_time_string(),
            fmt % args,
        ))

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, message, status=HTTPStatus.BAD_REQUEST):
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_svg(self, svg, status=HTTPStatus.OK):
        body = svg.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "image/svg+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/api/items":
            with ITEM_LOCK:
                items = load_items()
            self.send_json({"items": items})
            return
        if path == "/api/info":
            self.send_json({
                "name": "LanBox",
                "hostname": socket.gethostname(),
                "port": self.server.server_port,
                "max_upload_mb": MAX_UPLOAD_MB,
                "client_ttl_seconds": CLIENT_TTL_SECONDS,
                "background_client_ttl_seconds": BACKGROUND_CLIENT_TTL_SECONDS,
                "addresses": local_addresses(self.server.server_port),
            })
            return
        if path == "/api/qr.svg":
            params = parse_qs(parsed.query)
            raw_url = params.get("url", [""])[0]
            target_url = raw_url or (local_addresses(self.server.server_port) or [f"http://127.0.0.1:{self.server.server_port}"])[0]
            if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{1,180}", target_url):
                self.send_text("Invalid QR URL", HTTPStatus.BAD_REQUEST)
                return
            try:
                self.send_svg(qr_svg(target_url))
            except ValueError:
                self.send_text("QR URL is too long", HTTPStatus.BAD_REQUEST)
            return
        if path.startswith("/files/"):
            self.serve_uploaded_file(path, parsed.query)
            return
        self.serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/heartbeat":
            self.handle_heartbeat()
            return
        close_match = re.fullmatch(r"/api/clients/([A-Za-z0-9._-]+)/close", parsed.path)
        if close_match:
            self.handle_client_close(close_match.group(1))
            return
        pin_match = re.fullmatch(r"/api/items/([A-Za-z0-9-]+)/pin", parsed.path)
        if pin_match:
            self.handle_pin_item(pin_match.group(1))
            return
        save_match = re.fullmatch(r"/api/items/([A-Za-z0-9-]+)/save", parsed.path)
        if save_match:
            self.handle_pin_item(save_match.group(1), True)
            return
        if parsed.path != "/api/items":
            self.send_text("Not found", HTTPStatus.NOT_FOUND)
            return
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length > MAX_UPLOAD_BYTES:
            self.send_json({"error": f"上传内容超过限制：{MAX_UPLOAD_MB} MB"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return

        ctype = self.headers.get("Content-Type", "")
        if not ctype.startswith("multipart/form-data"):
            self.send_json({"error": "Content-Type must be multipart/form-data"}, HTTPStatus.BAD_REQUEST)
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": ctype,
                "CONTENT_LENGTH": str(content_length),
            },
        )

        text = (form.getfirst("text", "") or "").strip()
        title = (form.getfirst("title", "") or "").strip()
        files = []
        item_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(4).hex()
        item_dir = UPLOAD_DIR / item_id

        for field in form_file_fields(form, "files"):
            if not getattr(field, "filename", None):
                continue
            item_dir.mkdir(parents=True, exist_ok=True)
            original = safe_filename(field.filename)
            target = unique_path(item_dir, original)
            with target.open("wb") as out:
                shutil.copyfileobj(field.file, out)
            stored_name = target.name
            rel_url = f"/files/{quote(item_id)}/{quote(stored_name)}"
            files.append({
                "name": original,
                "stored": stored_name,
                "size": target.stat().st_size,
                "mime": field.type or mimetypes.guess_type(original)[0] or "application/octet-stream",
                "url": rel_url,
            })

        if not text and not files:
            if item_dir.exists():
                shutil.rmtree(item_dir, ignore_errors=True)
            self.send_json({"error": "请填写文本/链接，或选择至少一个文件"}, HTTPStatus.BAD_REQUEST)
            return

        item = {
            "id": item_id,
            "created_at": now_iso(),
            "client_ip": self.client_address[0],
            "saved": False,
            "saved_at": "",
            "title": title,
            "text": text,
            "files": files,
        }

        with ITEM_LOCK:
            items = load_items()
            items.insert(0, item)
            save_items(items)
        self.send_json({"item": item}, HTTPStatus.CREATED)

    def handle_heartbeat(self):
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(content_length) if content_length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            return
        client_id = str(payload.get("client_id", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{8,120}", client_id):
            self.send_json({"error": "Invalid client_id"}, HTTPStatus.BAD_REQUEST)
            return
        state = str(payload.get("state", "active")).strip()
        if state not in ("active", "background"):
            state = "active"
        with ACTIVE_LOCK:
            ACTIVE_CLIENTS[client_id] = {
                "seen_at": time.time(),
                "state": state,
            }
            prune_active_clients()
            active_count = len(ACTIVE_CLIENTS)
            counts = active_client_counts()
        self.send_json({
            "ok": True,
            "active_clients": active_count,
            "client_counts": counts,
            "ttl_seconds": CLIENT_TTL_SECONDS,
            "background_ttl_seconds": BACKGROUND_CLIENT_TTL_SECONDS,
        })

    def handle_client_close(self, client_id):
        with ACTIVE_LOCK:
            ACTIVE_CLIENTS.pop(client_id, None)
        self.send_json({"ok": True})

    def handle_pin_item(self, item_id, pinned=None):
        if pinned is None:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(content_length) if content_length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
                return
            pinned = bool(payload.get("pinned"))

        with ITEM_LOCK:
            items = load_items()
            for item in items:
                if item.get("id") == item_id:
                    item["saved"] = pinned
                    item["saved_at"] = now_iso() if pinned else ""
                    save_items(items)
                    self.send_json({"item": item})
                    return
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        match = re.fullmatch(r"/api/items/([A-Za-z0-9-]+)", parsed.path)
        if not match:
            self.send_text("Not found", HTTPStatus.NOT_FOUND)
            return
        item_id = match.group(1)
        with ITEM_LOCK:
            items = load_items()
            next_items = [item for item in items if item.get("id") != item_id]
            if len(next_items) == len(items):
                self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
                return
            save_items(next_items)
        shutil.rmtree(UPLOAD_DIR / item_id, ignore_errors=True)
        self.send_json({"ok": True})

    def serve_static(self, request_path):
        if request_path == "/":
            request_path = "/index.html"
        normalized = posixpath.normpath(unquote(request_path)).lstrip("/")
        if normalized.startswith(".."):
            self.send_text("Forbidden", HTTPStatus.FORBIDDEN)
            return
        target = PUBLIC_DIR / normalized
        if not target.exists() or not target.is_file():
            self.send_text("Not found", HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def serve_uploaded_file(self, request_path, query=""):
        parts = request_path.split("/", 3)
        if len(parts) != 4:
            self.send_text("Not found", HTTPStatus.NOT_FOUND)
            return
        item_id = unquote(parts[2])
        filename = safe_filename(unquote(parts[3]))
        if not re.fullmatch(r"[A-Za-z0-9-]+", item_id):
            self.send_text("Forbidden", HTTPStatus.FORBIDDEN)
            return
        target = UPLOAD_DIR / item_id / filename
        if not target.exists() or not target.is_file():
            self.send_text("Not found", HTTPStatus.NOT_FOUND)
            return
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        disposition = "inline" if parse_qs(query).get("inline", ["0"])[0] == "1" else "attachment"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(filename)}")
        self.end_headers()
        with target.open("rb") as src:
            shutil.copyfileobj(src, self.wfile)


def main():
    ensure_dirs()
    remove_unsaved_items_if_idle()
    host = os.environ.get("LANBOX_HOST", "0.0.0.0")
    port = int(os.environ.get("LANBOX_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), LanBoxHandler)
    threading.Thread(target=cleanup_loop, daemon=True).start()
    print_access_info(port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
