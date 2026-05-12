import json
import logging
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import requests

from telegram_bot import core
from telegram_bot.services.command_service import refresh_command_registry

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
        if self.path == "/api/events/registry-changed":
            import threading
            threading.Thread(target=refresh_command_registry, kwargs={
                             "force": True}, daemon=True).start()
            self._send_json(
                200,
                {
                    "status": "ok",
                    "reason": "refresh scheduled",
                    "revision": core.COMMAND_REGISTRY_REVISION,
                },
            )
            return
        if self.path == "/api/dispatch/send":
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                payload = json.loads(body) if body else {}

                chat_id = str(payload.get("target", "")).strip()
                message = str(payload.get("message", "")).strip()
                entity_payload = payload.get("payload")
                domain = str(payload.get("domain", "")).strip()
                entity_id = str(payload.get("entity_id", "")).strip()
                trace_id = str(self.headers.get(
                    "X-Trace-Id") or payload.get("trace_id") or "").strip() or uuid.uuid4().hex

                if not chat_id:
                    self._send_json(
                        400, {"status": "error", "detail": "target required"})
                    return

                if entity_payload and isinstance(entity_payload, dict):
                    title = entity_payload.get(
                        "title", entity_payload.get("summary", ""))
                    logger.info(
                        "event=buffering_alert_chat_id_domain_entity_trace_id Buffering alert | chat_id=%s domain=%s entity=%s trace_id=%s title='%s'",
                        chat_id, domain, entity_id, trace_id, str(title)[:60])
                    core.buffer_alert(
                        chat_id,
                        entity_payload,
                        domain,
                        entity_id,
                        trace_id=trace_id,
                    )
                    self._send_json(
                        200, {"status": "ok", "sent": True, "buffered": True})
                    return

                if not message:
                    self._send_json(
                        400, {"status": "error", "detail": "message or payload required"})
                    return

                try:
                    core.send_user_message(
                        chat_id,
                        message,
                        parse_mode="HTML",
                    )
                    self._send_json(200, {"status": "ok", "sent": True})
                except Exception as e:
                    self._send_json(400, {"status": "error", "detail": str(e)})
            except Exception as e:
                self._send_json(400, {"status": "error", "detail": str(e)})
            return
        self._send_json(404, {"status": "error", "detail": "not found"})

    def log_message(self, format: str, *args):
        return

    def _format_alert_with_oracle(self, entity_payload: dict[str, Any], domain: str, entity_id: str) -> str | None:
        """Call Oracle to format entity alert using AI"""
        return _format_single_alert_with_oracle(entity_payload, domain, entity_id)

    def _build_fallback_message(self, entity_payload: dict[str, Any], domain: str, entity_id: str) -> str:
        """Build conversational formatted alert when Oracle fails"""
        return build_alert_fallback_message(entity_payload, domain, entity_id)


def _format_single_alert_with_oracle(
    entity_payload: dict[str, Any],
    domain: str,
    entity_id: str,
    chat_id: str | int | None = None,
    trace_id: str | None = None,
) -> str | None:
    """Call Oracle to format entity alert using AI"""
    try:
        title = entity_payload.get("title") or entity_payload.get(
            "summary") or "questa proprietà"

        effective_instructions = (
            core.build_client_instructions_for_chat(str(chat_id))
            if chat_id is not None
            else core.TELEGRAM_ORACLE_CLIENT_INSTRUCTIONS
        )
        request_payload = {
            "command": f"alert:{domain}",
            "payload": {
                **entity_payload,
                "delivery_context": {
                    "domain": domain,
                    "entity_id": entity_id,
                    "chat_id": str(chat_id) if chat_id is not None else "",
                    "session_settings": core.get_session_settings(str(chat_id)) if chat_id is not None else {},
                },
            },
            "response_prompt": (
                "Sei Hestia e stai PROATTIVAMENTE informando l'utente di una nuova proprietà che corrisponde alle sue preferenze. "
                "Scrivi come se TU stessi iniziando la conversazione per dirgli: 'Ho trovato questa casa per te!'. "
                f"Includi il TITOLO COMPLETO ('{title}'), indirizzo, prezzo, superficie e caratteristiche chiave. "
                "Quando metti il link, usa il TITOLO della proprietà come testo del link (es: <a href=\"URL\">Appartamento tre camere in Via Roma</a>), MAI testi generici come 'Apri annuncio'. "
                "Sii entusiasta ma professionale. Usa emoji appropriate (🏠 📍 💶 📐). "
                "NON usare saluti come 'Ciao' o 'Ecco'. Inizia direttamente con l'informazione importante."
            ),
            "client_instructions": effective_instructions,
        }
        response = requests.post(
            core.ORACLE_FORMAT_API_URL,
            json=request_payload,
            headers={"X-Trace-Id": str(trace_id or "").strip()
                     } if str(trace_id or "").strip() else None,
            timeout=12,
        )
        if response.status_code != 200:
            return None
        text = str((response.json() or {}).get("text", "")).strip()
        if not text:
            return None
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned = []
        for i, line in enumerate(lines):
            if i == 0:
                stripped = line.strip().lower()
                if any(stripped.startswith(prefix) for prefix in ("ciao", "salve", "ecco", "qui", "sure", "here", "certo")):
                    continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()
    except Exception:
        return None


def build_alert_fallback_message(entity_payload: dict[str, Any], domain: str, entity_id: str) -> str:
    """Build conversational formatted alert when Oracle fails"""
    title = entity_payload.get("title") or entity_payload.get(
        "summary") or "Nuova proprietà"
    url = entity_payload.get("url") or entity_id
    address = entity_payload.get("address", "")
    price = entity_payload.get("price")

    lines: list[str] = []
    if url:
        lines.append(f"🏠 <a href=\"{url}\"><b>{title}</b></a>")
    else:
        lines.append(f"🏠 <b>{title}</b>")

    details: list[str] = []
    if address:
        details.append(f"📍 {address}")
    if price:
        details.append(f"€ {price}")
    specs = entity_payload.get("specs") if isinstance(
        entity_payload.get("specs"), dict) else {}
    for key in ("surface_m2", "m2", "surface"):
        if key in specs and specs.get(key) is not None:
            details.append(f"{specs[key]} m²")
            break
    if details:
        lines.append(" · ".join(details))

    return "\n".join(lines)


def format_multiple_alerts_with_oracle(
    alerts: list[dict[str, Any]],
    chat_id: str | int | None = None,
    trace_id: str | None = None,
) -> str | None:
    """Format multiple consecutive alerts as one continuous chat message via Oracle"""
    if not alerts:
        return None

    # Create a combined payload that represents all alerts
    combined_payload = {
        "multiple_alerts": True,
        "count": len(alerts),
        "properties": [alert.get("payload", {}) for alert in alerts],
        "alert_meta": [
            {
                "domain": str(alert.get("domain") or "").strip(),
                "entity_id": str(alert.get("entity_id") or "").strip(),
            }
            for alert in alerts
        ],
        "delivery_context": {
            "chat_id": str(chat_id) if chat_id is not None else "",
            "session_settings": core.get_session_settings(str(chat_id)) if chat_id is not None else {},
            "domains": sorted({str(alert.get("domain") or "").strip() for alert in alerts if str(alert.get("domain") or "").strip()}),
            "trace_id": str(trace_id or "").strip(),
        },
    }

    try:
        effective_instructions = (
            core.build_client_instructions_for_chat(str(chat_id))
            if chat_id is not None
            else core.TELEGRAM_ORACLE_CLIENT_INSTRUCTIONS
        )
        request_payload = {
            "command": f"alert:multi",
            "payload": combined_payload,
            "response_prompt": (
                "Sei Hestia e stai PROATTIVAMENTE informando l'utente di MULTIPLE proprietà che corrispondono alle sue preferenze. "
                "Scrivi come se TU stessi iniziando UNA conversazione unica e fluida per condividere queste proprietà, NON come elenco a pallini. "
                "Parla come stessi chattando normalmente: 'Ho trovato diverse proprietà interessanti per te' e poi continua presentandole "
                "come una continuazione naturale della stessa conversazione. "
                "Usa transizioni fluide tra le proprietà (es: 'Inoltre', 'Un'altra opzione', 'Tra le opzioni mi piace anche'). "
                "Per ogni proprietà includi titolo, indirizzo, prezzo e caratteristiche. "
                "Quando metti i link, usa il TITOLO della proprietà come testo (es: <a href=\"URL\">Appartamento tre camere</a>), MAI testi generici. "
                "Sii entusiasta ma professionale. Usa emoji appropriati. "
                "NON usare saluti iniziali o frasi di apertura. Inizia DIRETTAMENTE con l'informazione."
            ),
            "client_instructions": effective_instructions,
        }
        response = requests.post(
            core.ORACLE_FORMAT_API_URL,
            json=request_payload,
            headers={"X-Trace-Id": str(trace_id or "").strip()
                     } if str(trace_id or "").strip() else None,
            timeout=15,
        )
        if response.status_code != 200:
            return None
        text = str((response.json() or {}).get("text", "")).strip()
        if not text:
            return None

        # Remove intro lines
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned = []
        for i, line in enumerate(lines):
            if i == 0:
                stripped = line.strip().lower()
                if any(stripped.startswith(prefix) for prefix in ("ciao", "salve", "ecco", "qui", "sure", "here", "certo")):
                    continue
            cleaned.append(line)
        return "\n".join(cleaned).strip()
    except Exception:
        return None


def run_control_api():
    server = ThreadingHTTPServer(
        ("0.0.0.0", core.TELEGRAM_CONTROL_PORT), ControlRequestHandler)
    server.serve_forever()
