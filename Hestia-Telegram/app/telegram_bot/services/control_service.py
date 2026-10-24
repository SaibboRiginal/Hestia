"""Telegram's small control server: health, logs, settings push from Themis, Hub registry changes, the chat queue
drain and Hermes notifications (``/api/notify``)."""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import telegram_settings
from telegram_bot import core

logger = logging.getLogger("hestia_telegram.control")


class ControlRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict[str, Any]):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except BrokenPipeError:
            logger.debug(
                "event=client_disconnected_before_receiving_response Client disconnected before receiving response")
        except ConnectionResetError:
            logger.debug(
                "event=connection_reset_peer Connection reset by peer")

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "telegram"})
            return
        if self.path == "/api/settings/effective":
            self._send_json(200, telegram_settings.effective_payload())
            return
        if self.path.startswith("/api/logs"):
            from urllib.parse import parse_qs, urlsplit

            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            try:
                limit = int((query.get("limit") or ["200"])[0])
            except Exception:
                limit = 200
            level = (query.get("level") or [None])[0]
            contains = (query.get("contains") or [None])[0]
            rows = core.LOG_BUFFER.query(
                limit=limit, level=level, contains=contains)
            self._send_json(
                200,
                {
                    "service": "hestia_telegram",
                    "count": len(rows),
                    "logs": rows,
                },
            )
            return
        self._send_json(404, {"status": "error", "detail": "not found"})

    def do_POST(self):
        if self.path == "/api/settings/reload":
            # Themis pushes changed values here (via Hub) so live settings apply at once.
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length).decode("utf-8") if content_length else ""
                payload = json.loads(body) if body else {}
                self._send_json(200, telegram_settings.reload_payload(payload if isinstance(payload, dict) else {}))
            except Exception as e:
                logger.warning("event=settings_reload_failed error=%s", e)
                self._send_json(400, {"status": "error", "detail": str(e)})
            return
        if self.path == "/api/events/registry-changed":
            # Tools changed somewhere: the catalog reloads; menus pick it up at the next tap.
            from telegram_bot import catalog
            threading.Thread(target=catalog.refresh, kwargs={"force": True}, daemon=True).start()
            self._send_json(200, {"status": "ok", "reason": "refresh scheduled"})
            return
        if self.path == "/api/chat-queue/drain":
            # Oracle back (Chronos presence relax): answer queued chat messages in the background.
            from telegram_bot.services.chat_queue import drain_async
            self._send_json(202, {"status": "started" if drain_async("chronos") else "busy"})
            return
        if self.path == "/api/notify":
            # Hermes notification client contract (notification / update / retract).
            from telegram_bot.services.notifications import handle_notify
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                status, result = handle_notify(json.loads(body) if body else {})
                self._send_json(status, result)
            except Exception as e:
                self._send_json(400, {"status": "error", "detail": str(e)})
            return
        self._send_json(404, {"status": "error", "detail": "not found"})

    def log_message(self, format: str, *args):
        return


def run_control_api():
    server = ThreadingHTTPServer(
        ("0.0.0.0", core.TELEGRAM_CONTROL_PORT), ControlRequestHandler)
    server.serve_forever()
