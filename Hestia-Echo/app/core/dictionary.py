"""Personal dictionary for listening (Cindy 17, dossier docs/work/2026-10-24-tutto-brainstorm-cindy W4).

Names and terms the engine gets wrong (people, places, «Hygieia»…) are passed to every listening engine as a hint
(Whisper ``initial_prompt``, OpenAI-compatible ``prompt``). The dictionary fills itself: when the owner corrects
a transcript (``learn(heard, corrected)``) the new words become candidates and a word is confirmed after
``echo.dizionario.conferme`` corrections (default 2). Words added by hand (page «Voce», tool ``voce_parola``) are
confirmed at once; the owner removes any word. Rows: Archive ``echo-store`` ``kind=word`` (id = normalised word).
"""
from __future__ import annotations

import logging
import re
import time
import unicodedata

logger = logging.getLogger("hestia_echo.dictionary")

_WORD = re.compile(r"[A-Za-zÀ-ÿ][\wÀ-ÿ'’-]{2,39}")
MAX_HINT_WORDS = 80
_CACHE_S = 300


def norm(word: str) -> str:
    w = unicodedata.normalize("NFKC", str(word or "")).strip().strip("'’-").lower()
    return re.sub(r"\s+", " ", w)


def new_words(heard: str, corrected: str) -> list[str]:
    """Words of the correction that the engine did not hear (as written by the owner, first spelling kept)."""
    seen = {norm(w) for w in _WORD.findall(heard or "")}
    out, done = [], set()
    for w in _WORD.findall(corrected or ""):
        n = norm(w)
        if n not in seen and n not in done:
            out.append(w)
            done.add(n)
    return out[:20]


class Dictionary:
    def __init__(self, keep, get):
        self.keep = keep
        self.get = get
        self._cache: tuple[float, list[dict]] | None = None

    def _all(self) -> list[dict]:
        if self._cache and time.monotonic() - self._cache[0] < _CACHE_S:
            return self._cache[1]
        rows = [r for r in self.keep._rows(kind="word", limit=5000) if not r.get("deleted")]
        self._cache = (time.monotonic(), rows)
        return rows

    def _put(self, row_id: str, data: dict, deleted: bool = False) -> None:
        from .keep import now
        stamp = now().isoformat()
        self.keep._put([{"kind": "word", "id": row_id, "at": data.get("at") or stamp, "updated_at": stamp,
                         "data": data, "deleted": deleted}])
        self._cache = None

    def needed(self) -> int:
        try:
            return max(1, int(self.get("echo.dizionario.conferme", 2)))
        except (TypeError, ValueError):
            return 2

    def list(self) -> list[dict]:
        return sorted(((r.get("data") or {}) for r in self._all()), key=lambda d: (d.get("status") != "confirmed",
                                                                                  norm(d.get("word"))))

    def confirmed(self) -> list[str]:
        return [d["word"] for d in self.list() if d.get("status") == "confirmed" and d.get("word")]

    def hint(self) -> str:
        words = self.confirmed()[:MAX_HINT_WORDS]
        return ", ".join(words) + "." if words else ""

    def add(self, word: str, source: str = "manual") -> dict:
        w = str(word or "").strip()
        if not _WORD.fullmatch(w) and not all(_WORD.fullmatch(p) for p in w.split()):
            raise ValueError("parola non valida")
        data = {"word": w, "status": "confirmed", "count": self.needed(), "source": source}
        self._put(norm(w), data)
        logger.info("event=voice_word_added source=%s", source)
        return data

    def remove(self, word: str) -> bool:
        key = norm(word)
        row = next((r for r in self._all() if r.get("id") == key), None)
        if not row:
            return False
        self._put(key, {**(row.get("data") or {}), "status": "removed"}, deleted=True)
        logger.info("event=voice_word_removed")
        return True

    def learn(self, heard: str, corrected: str) -> dict:
        """One correction by the owner: candidates count up, confirmed at ``needed()``."""
        rows = {r.get("id"): (r.get("data") or {}) for r in self._all()}
        confirmed, candidates = [], []
        for w in new_words(heard, corrected):
            key = norm(w)
            d = rows.get(key) or {"word": w, "status": "candidate", "count": 0, "source": "correction"}
            if d.get("status") == "confirmed":
                continue
            d["count"] = int(d.get("count") or 0) + 1
            if d["count"] >= self.needed():
                d["status"] = "confirmed"
                confirmed.append(d["word"])
            else:
                candidates.append(d["word"])
            self._put(key, d)
        if confirmed or candidates:
            logger.info("event=voice_dictionary_learned confirmed=%d candidates=%d", len(confirmed), len(candidates))
        return {"confirmed": confirmed, "candidates": candidates}
