"""SkillCurator — Athena daily cycle skill creation and lifecycle management.

Hermes Agent pattern: the Curator runs once per day, reads Oracle session
summaries, clusters them by embedding similarity, creates new skills from
recurring patterns, and manages skill lifecycle (deprecate, merge, promote).

All Archive interaction is via Hub routing (Rulebook 1.3).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Callable

import requests

logger = logging.getLogger("hestia_athena.skill_curator")


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = (sum(x * x for x in a)) ** 0.5
    nb = (sum(x * x for x in b)) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class SkillCurator:
    """Daily skill creation and lifecycle management.

    Parameters
    ----------
    hub_api_url: Hub base URL for Archive routing.
    embed_fn: Callable that returns a 768-dim embedding vector for text.
    oracle_route: Hub route prefix for Oracle (for hint emission).
    """

    def __init__(
        self,
        hub_api_url: str,
        embed_fn: Callable[[str], list[float]],
        oracle_route: str = "",
    ) -> None:
        self._hub = hub_api_url.rstrip("/")
        self._embed = embed_fn
        self._oracle_route = oracle_route.rstrip("/") if oracle_route else ""

        # Thresholds — all env-var configurable (Rulebook 1.4)
        self._min_sessions = int(os.getenv("ATHENA_SKILL_MIN_SESSIONS", "3"))
        self._sim_threshold = float(os.getenv("ATHENA_SKILL_SIM_THRESHOLD", "0.90"))
        self._dedup_threshold = float(os.getenv("ATHENA_SKILL_DEDUP_THRESHOLD", "0.95"))
        self._stale_days = int(os.getenv("ATHENA_SKILL_STALE_DAYS", "30"))
        self._hard_delete_days = int(os.getenv("ATHENA_SKILL_HARD_DELETE_DAYS", "90"))
        self._core_use_count = int(os.getenv("ATHENA_SKILL_CORE_USE_COUNT", "50"))

    # ── Public API ──────────────────────────────────────────────────────────

    def run_cycle(self) -> dict:
        """Execute one daily skill curation cycle.

        Returns a summary dict for logging.
        """
        t0 = time.perf_counter()
        summary = {"created": 0, "updated": 0, "deprecated": 0,
                   "merged": 0, "deleted": 0, "promoted": 0}

        try:
            sessions = self._fetch_session_summaries()
            if not sessions:
                logger.debug("event=skill_curator_no_sessions")
                return summary

            clusters = self._cluster_sessions(sessions)
            for cluster in clusters:
                if len(cluster) < self._min_sessions:
                    continue
                created_or_updated = self._upsert_skill(cluster)
                if created_or_updated == "created":
                    summary["created"] += 1
                elif created_or_updated == "updated":
                    summary["updated"] += 1

            # Lifecycle management
            lifecycle = self._manage_lifecycle()
            summary.update(lifecycle)

            elapsed_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(
                "event=skill_curator_cycle_done created=%d updated=%d "
                "deprecated=%d merged=%d deleted=%d promoted=%d "
                "sessions=%d clusters=%d elapsed_ms=%d",
                summary["created"], summary["updated"],
                summary["deprecated"], summary["merged"],
                summary["deleted"], summary["promoted"],
                len(sessions), len(clusters), elapsed_ms,
            )
        except Exception as exc:
            logger.warning("event=skill_curator_cycle_failed error=%s", exc)

        return summary

    # ── Session summaries ───────────────────────────────────────────────────

    def _fetch_session_summaries(self) -> list[dict]:
        """Fetch recent session summaries from Archive (last 24h)."""
        try:
            result = self._route_archive(
                "GET", "/api/entities", query={
                    "entity_type": "session_summary",
                    "limit": "500",
                })
            if not isinstance(result, list):
                return []
            # Filter to last 24h client-side (Archive may not support time filter)
            cutoff = time.time() - 86400
            recent = []
            for s in result:
                if not isinstance(s, dict):
                    continue
                created = s.get("created_at")
                if isinstance(created, str):
                    try:
                        from datetime import datetime
                        created_ts = datetime.fromisoformat(
                            created.replace("Z", "+00:00")).timestamp()
                        if created_ts < cutoff:
                            continue
                    except Exception:
                        pass
                if s.get("success") and isinstance(s.get("embedding"), list):
                    recent.append(s)
            return recent
        except Exception as exc:
            logger.warning("event=skill_curator_fetch_failed error=%s", exc)
            return []

    # ── Clustering ──────────────────────────────────────────────────────────

    def _cluster_sessions(self, sessions: list[dict]) -> list[list[dict]]:
        """Cluster sessions by domain + embedding similarity.

        Simple greedy clustering: for each session, find best-matching cluster
        or start a new one.
        """
        clusters: list[list[dict]] = []
        for session in sessions:
            emb = session.get("embedding")
            if not isinstance(emb, list):
                continue
            best_idx = -1
            best_sim = 0.0
            for i, cluster in enumerate(clusters):
                # Compare against cluster centroid (first session's embedding)
                cluster_emb = cluster[0].get("embedding")
                if isinstance(cluster_emb, list):
                    sim = _cosine(emb, cluster_emb)
                    if sim > best_sim:
                        best_sim = sim
                        best_idx = i
            if best_idx >= 0 and best_sim >= self._sim_threshold:
                clusters[best_idx].append(session)
            else:
                clusters.append([session])
        return clusters

    # ── Skill upsert ────────────────────────────────────────────────────────

    def _upsert_skill(self, cluster: list[dict]) -> str:
        """Create or update a skill from a session cluster.

        Extracts the most common tool_sequence across sessions in the cluster.
        Returns "created" or "updated".
        """
        # Find most common tool sequence
        seq_counts: dict[str, tuple[int, list[dict]]] = {}
        for s in cluster:
            seq = s.get("tool_sequence")
            if not isinstance(seq, list):
                continue
            key = json.dumps(
                [{"tool": t.get("tool", ""), "ok": t.get("ok", False)} for t in seq],
                sort_keys=True,
            )
            count, _ = seq_counts.get(key, (0, seq))
            seq_counts[key] = (count + 1, seq)

        if not seq_counts:
            return "none"
        best_key = max(seq_counts, key=lambda k: seq_counts[k][0])
        _, best_seq = seq_counts[best_key]

        # Build skill embedding from centroid of cluster
        embeddings = [s.get("embedding") for s in cluster if isinstance(s.get("embedding"), list)]
        if not embeddings:
            return "none"
        dim = len(embeddings[0])
        centroid = [sum(e[i] for e in embeddings) / len(embeddings) for i in range(dim)]

        # Domain from cluster
        domain = cluster[0].get("domain", "general")

        # Generate skill name + description (simple heuristic — no LLM call)
        tool_names = [t.get("tool", "") for t in best_seq if t.get("tool")]
        skill_name = f"{domain}_{'_'.join(tool_names[:3])}".replace(".", "_")[:64]
        description = f"Sequenza {', '.join(tool_names)} per dominio {domain}"

        # Check if similar skill already exists
        existing = self._find_similar_skill(centroid, domain)
        if existing:
            self._update_skill(existing["id"], use_count=existing.get("use_count", 0))
            return "updated"

        # Create new skill
        self._create_skill(
            name=skill_name,
            description=description,
            tool_sequence=best_seq,
            embedding=centroid,
            domain=domain,
        )
        return "created"

    def _find_similar_skill(self, embedding: list[float], domain: str) -> dict | None:
        """Find existing skill with similar embedding."""
        try:
            result = self._route_archive(
                "POST", "/api/memory/search/similar",
                body={
                    "embedding": embedding,
                    "memory_class": "skill",
                    "domain": domain,
                    "limit": 3,
                })
            if isinstance(result, tuple):
                _, result = result
            if isinstance(result, list) and result:
                best = result[0]
                if isinstance(best, dict) and best.get("_similarity", 0) >= self._dedup_threshold:
                    return best
        except Exception as exc:
            logger.debug("event=skill_curator_find_similar_failed error=%s", exc)
        return None

    def _create_skill(
        self, name: str, description: str,
        tool_sequence: list[dict], embedding: list[float], domain: str,
    ) -> None:
        """Create a new skill in Archive."""
        try:
            self._route_archive("POST", "/api/memory", body={
                "fact": json.dumps({
                    "skill_name": name,
                    "description": description,
                    "tool_sequence": tool_sequence,
                }),
                "domain": domain,
                "weight": 1.0,
                "memory_class": "skill",
                "embedding": embedding,
                "extra_data": {
                    "skill_name": name,
                    "description": description,
                    "tool_sequence": tool_sequence,
                    "use_count": 0,
                    "success_rate": 1.0,
                    "created_by": "athena_curator",
                },
            })
            logger.info("event=skill_created name=%s domain=%s tools=%d",
                        name, domain, len(tool_sequence))
            self._emit_hint(f"Nuova skill creata: {name} ({domain})")
        except Exception as exc:
            logger.warning("event=skill_create_failed name=%s error=%s", name, exc)

    def _update_skill(self, skill_id: int, use_count: int = 0) -> None:
        """Refresh a skill's metadata."""
        try:
            self._route_archive("PATCH", f"/api/memory/{skill_id}", body={
                "is_active": True,
                "weight": min(2.0, 1.0 + use_count * 0.01),
            })
        except Exception as exc:
            logger.debug("event=skill_update_failed id=%d error=%s", skill_id, exc)

    # ── Lifecycle management ────────────────────────────────────────────────

    def _manage_lifecycle(self) -> dict:
        """Deprecate stale, merge duplicates, promote core, hard-delete dead."""
        try:
            all_skills = self._route_archive(
                "GET", "/api/memory/active", query={
                    "memory_class": "skill", "limit": "200",
                }) or []
            if not isinstance(all_skills, list):
                return {}
        except Exception:
            return {}

        result = {"deprecated": 0, "merged": 0, "deleted": 0, "promoted": 0}
        now = time.time()
        seen_embeddings: list[tuple[list[float], dict]] = []

        for skill in all_skills:
            if not isinstance(skill, dict):
                continue
            sid = skill.get("id")
            extra = skill.get("extra_data") or {}
            use_count = int(extra.get("use_count", 0))
            success_rate = float(extra.get("success_rate", 1.0))
            last_used_raw = extra.get("last_used")
            emb = skill.get("embedding")

            # Parse last_used timestamp
            last_used_ts = 0.0
            if isinstance(last_used_raw, str):
                try:
                    from datetime import datetime
                    last_used_ts = datetime.fromisoformat(
                        last_used_raw.replace("Z", "+00:00")).timestamp()
                except Exception:
                    pass

            days_since_use = (now - last_used_ts) / 86400 if last_used_ts > 0 else 999

            # ── Lifecycle rules (Hermes Agent pattern) ──────────────────
            if success_rate < 0.5:
                self._deprecate_skill(sid)
                result["deprecated"] += 1
                continue

            if days_since_use > self._hard_delete_days and use_count < 3:
                self._delete_skill(sid)
                result["deleted"] += 1
                continue

            if days_since_use > self._stale_days:
                self._deprecate_skill(sid)
                result["deprecated"] += 1
                continue

            if use_count > self._core_use_count and success_rate > 0.95:
                self._promote_skill(sid)
                result["promoted"] += 1

            # Dedup check
            if isinstance(emb, list):
                for prev_emb, prev_skill in seen_embeddings:
                    if _cosine(emb, prev_emb) >= self._dedup_threshold:
                        self._merge_skills(prev_skill.get("id"), sid, use_count)
                        result["merged"] += 1
                        break
                else:
                    seen_embeddings.append((emb, skill))

        return result

    def _deprecate_skill(self, skill_id: int) -> None:
        try:
            self._route_archive("PATCH", f"/api/memory/{skill_id}", body={
                "is_active": False,
            })
        except Exception as exc:
            logger.debug("event=skill_deprecate_failed id=%d error=%s", skill_id, exc)

    def _delete_skill(self, skill_id: int) -> None:
        logger.info("event=skill_hard_delete id=%d", skill_id)
        # Archive currently has no DELETE for memory — mark inactive with zero weight
        self._deprecate_skill(skill_id)

    def _promote_skill(self, skill_id: int) -> None:
        try:
            self._route_archive("PATCH", f"/api/memory/{skill_id}", body={
                "is_active": True,
                "weight": 3.0,
            })
        except Exception as exc:
            logger.debug("event=skill_promote_failed id=%d error=%s", skill_id, exc)

    def _merge_skills(self, keep_id: int, remove_id: int, use_count: int) -> None:
        logger.info("event=skill_merge keep=%d remove=%d", keep_id, remove_id)
        self._deprecate_skill(remove_id)
        self._update_skill(keep_id, use_count)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _route_archive(self, method: str, path: str,
                       body: dict | None = None,
                       query: dict | None = None) -> object:
        """Route a request to Archive via Hub."""
        url = f"{self._hub}/route/archive{path}"
        params = {k: str(v) for k, v in (query or {}).items()}
        try:
            if method == "GET":
                resp = requests.get(url, params=params, timeout=10)
            elif method == "POST":
                resp = requests.post(url, json=body, params=params, timeout=10)
            elif method == "PATCH":
                resp = requests.patch(url, json=body, params=params, timeout=10)
            else:
                return None
            if resp.status_code >= 400:
                return None
            return resp.json()
        except Exception:
            return None

    def _emit_hint(self, message: str) -> None:
        """Emit a hint to Oracle via the existing Athena hints endpoint."""
        if not self._oracle_route:
            return
        try:
            requests.post(
                f"{self._hub}/route{self._oracle_route}/api/athena/hints",
                json={"message": message, "source": "skill_curator"},
                timeout=5,
            )
        except Exception:
            pass
