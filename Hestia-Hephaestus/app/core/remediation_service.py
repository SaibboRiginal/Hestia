from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import requests

from ..forge import forge_settings as fs
from .models import RemediationApproveRequest, RemediationRequest, RemediationRollbackRequest, RunbookDefinition


class RemediationService:
    def __init__(
        self,
        *,
        logger,
        hub_api_url: str,
        notify_target: str,
        baseline_ref: str,
        maintenance_paths: list[str],
    ) -> None:
        self._logger = logger
        self._hub_api_url = hub_api_url.rstrip("/")
        self._notify_target = notify_target
        self._baseline_ref = baseline_ref
        self._maintenance_paths = [
            path.strip() for path in maintenance_paths if str(path).strip()]
        self._tasks_lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        # Assistant agenda: pending repairs are visible, failed ones are retried as
        # agenda tasks, the last failure escalates to Forge (never abandoned).
        self.agenda = None
        self.escalate = None  # callable(task) -> str | None (Forge task id)

    # Central settings (Themis), read at use time (live).
    @property
    def _execution_timeout_seconds(self) -> float:
        return fs.get_float(fs.REMEDIATE_TIMEOUT, 5.0)

    @property
    def _require_approval_for_mutation(self) -> bool:
        return fs.get_bool(fs.REMEDIATE_REQUIRE_APPROVAL)

    @property
    def _allow_auto_approve_non_prod(self) -> bool:
        return fs.get_bool(fs.REMEDIATE_AUTO_APPROVE_NON_PROD)

    @property
    def _retry_minutes(self) -> int:
        return fs.get_int(fs.REPAIR_RETRY_MINUTES, 1)

    @property
    def _max_attempts(self) -> int:
        return fs.get_int(fs.REPAIR_MAX_ATTEMPTS, 1)

    def attach_agenda(self, agenda, escalate=None) -> None:
        self.agenda = agenda
        self.escalate = escalate

    def _agenda_key(self, task: dict[str, Any]) -> str:
        return f"hephaestus.repair.{task['task_id']}"

    def _agenda_sync(self, task: dict[str, Any]) -> None:
        """Mirror a remediation task in Hestia's agenda (best-effort, async)."""
        if self.agenda is None:
            return
        snapshot = dict(task)

        def _run() -> None:
            key = self._agenda_key(snapshot)
            state = snapshot.get("state")
            label = f"{snapshot.get('service')}: {snapshot.get('issue')}"
            try:
                if state == "pending_approval":
                    self.agenda.show(key, f"🛠️ Riparazione da approvare — {label}",
                                     datetime.now(timezone.utc),
                                     description=f"Runbook {snapshot.get('runbook_id')}. "
                                                 f"Approva: \"approva riparazione {snapshot['task_id'][:8]}\".",
                                     params={"task_id": snapshot["task_id"]})
                elif state == "failed" and not snapshot.get("dry_run"):
                    attempts = int(snapshot.get("attempts") or 1)
                    if attempts < self._max_attempts:
                        when = datetime.now(timezone.utc) + timedelta(minutes=self._retry_minutes * attempts)
                        self.agenda.plan(
                            key, f"🔁 Ritenta riparazione ({attempts + 1}/{self._max_attempts}) — {label}", when,
                            action={"service": "hephaestus",
                                    "path": f"/api/hephaestus/remediate/{snapshot['task_id']}/retry",
                                    "method": "POST", "body": {"requested_by": "agenda"},
                                    "timeout_seconds": 60},
                            description="Riparazione fallita: nuovo tentativo programmato. "
                                        "Sposta/annulla dall'agenda di Hestia.",
                            params={"task_id": snapshot["task_id"], "attempt": attempts + 1})
                    else:
                        self.agenda.done(key)
                elif state in {"succeeded", "rolled_back", "escalated"}:
                    self.agenda.done(key)
            except Exception as exc:
                self._logger.debug("event=remediation_agenda_sync_failed task_id=%s error=%s",
                                   snapshot.get("task_id"), exc)

        threading.Thread(target=_run, daemon=True, name="remediation-agenda").start()

    def retry_task(self, task_id: str, requested_by: str = "agenda") -> dict[str, Any] | None:
        """Re-run a failed remediation (agenda retry). After the last attempt the
        problem goes to Forge as a code-fix task (permission modes apply)."""
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if task.get("state") != "failed":
                return task
            task["attempts"] = int(task.get("attempts") or 1) + 1
            task = self._execute_task(task, approved_by=f"retry:{requested_by}")
            self._tasks[task_id] = task
        if task.get("state") == "failed" and int(task.get("attempts") or 1) >= self._max_attempts:
            forge_id = None
            if self.escalate is not None:
                try:
                    forge_id = self.escalate(task)
                except Exception as exc:
                    self._logger.warning("[🔄] event=remediation_escalation_failed task_id=%s error=%s",
                                         task_id, exc)
            if forge_id:
                with self._tasks_lock:
                    task["state"] = "escalated"
                    task["forge_task_id"] = forge_id
                    self._append_task_note(task, f"Escalated to Forge task {forge_id}")
        self._agenda_sync(task)
        self._notify_change(
            event_type="remediation.retried",
            task=task,
            message=(f"Hephaestus retry {task.get('attempts')}/{self._max_attempts} for task={task_id}: "
                     f"state={task.get('state')}"
                     + (f" → Forge {task.get('forge_task_id')}" if task.get("forge_task_id") else "")),
        )
        return task

    def _notify_change(self, event_type: str, task: dict[str, Any], message: str) -> None:
        self._logger.info(
            "event=hephaestus_change_notification event_type=%s task_id=%s message=%s",
            event_type,
            str(task.get("task_id") or ""),
            message,
        )
        if not self._notify_target:
            return
        payload = {
            "domain": "system",
            "event_type": "hephaestus.change",
            "entity_id": str(task.get("task_id") or "hephaestus-task"),
            "payload": {
                "_message": message,
                "task_id": str(task.get("task_id") or ""),
                "event_type": event_type,
                "task": task,
                "notify_target": self._notify_target,
            },
        }
        try:
            requests.post(
                f"{self._hub_api_url}/route/hermes/api/events/ingest",
                json={
                    "method": "POST",
                    "headers": {},
                    "query": {},
                    "body": payload,
                    "timeout_seconds": 8,
                },
                timeout=9,
            )
        except Exception as error:
            self._logger.warning(
                "event=hephaestus_notify_failed_non_fatal Notification dispatch failed (non-fatal): %s",
                error,
            )

    def _append_task_note(self, task: dict[str, Any], note: str) -> None:
        notes = task.get("notifications") if isinstance(
            task.get("notifications"), list) else []
        notes.append(
            {"ts": datetime.now(timezone.utc).isoformat(), "note": note})
        task["notifications"] = notes

    def _route_through_hub(
        self,
        *,
        service: str,
        path: str,
        body: dict[str, Any],
    ) -> tuple[bool, dict[str, Any]]:
        route_url = f"{self._hub_api_url}/route/{service}/{path.lstrip('/')}"
        envelope = {
            "method": "POST",
            "headers": {},
            "query": {},
            "body": body,
            "timeout_seconds": self._execution_timeout_seconds,
        }
        try:
            response = requests.post(
                route_url,
                json=envelope,
                timeout=self._execution_timeout_seconds + 2.0,
            )
            if response.status_code != 200:
                return False, {
                    "status": "error",
                    "error": f"hub_route_status_{response.status_code}",
                    "route": route_url,
                    "detail": response.text[:500],
                }

            routed_payload = response.json() if response.content else {}
            status_code = int((routed_payload or {}).get("status_code", 500))
            payload = (routed_payload or {}).get("payload")
            if status_code >= 400:
                return False, {
                    "status": "error",
                    "error": f"service_status_{status_code}",
                    "route": route_url,
                    "payload": payload,
                }

            if isinstance(payload, dict):
                return True, payload
            return True, {"payload": payload}
        except Exception as error:
            return False, {
                "status": "error",
                "error": str(error),
                "route": route_url,
            }

    def _execute_maintenance(self, task: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        service = str(task.get("service") or "").strip().lower()
        if not service:
            return False, {"status": "error", "error": "missing_target_service"}

        body = {
            "source": "hephaestus",
            "task_id": str(task.get("task_id") or ""),
            "issue": str(task.get("issue") or ""),
            "requested_action": str(task.get("requested_action") or "runbook_autoselect"),
            "environment": str(task.get("environment") or "dev"),
            "dry_run": bool(task.get("dry_run")),
            "metadata": task.get("metadata") if isinstance(task.get("metadata"), dict) else {},
        }

        last_error: dict[str, Any] = {
            "status": "error",
            "error": "no_maintenance_path_succeeded",
        }
        for template in self._maintenance_paths:
            maintenance_path = template.replace("$service", service)
            ok, response_payload = self._route_through_hub(
                service=service,
                path=maintenance_path,
                body=body,
            )
            if ok:
                return True, {
                    "target_service": service,
                    "maintenance_path": maintenance_path,
                    "response": response_payload,
                }
            last_error = {
                "status": "error",
                "target_service": service,
                "maintenance_path": maintenance_path,
                "error": response_payload,
            }

        return False, last_error

    def _approval_required(self, request: RemediationRequest) -> bool:
        if request.dry_run:
            return False
        if request.environment.lower() == "prod":
            return True
        return self._require_approval_for_mutation

    def _execute_task(self, task: dict[str, Any], approved_by: str, note: str | None = None) -> dict[str, Any]:
        t_task = time.perf_counter()
        task["state"] = "running"
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._append_task_note(task, f"Execution started by {approved_by}")
        self._logger.info(
            "event=remediation_execution_start task_id=%s runbook=%s approved_by=%s",
            task.get("task_id"),
            task.get("runbook_id"),
            approved_by,
        )

        succeeded, execution_result = self._execute_maintenance(task)

        task["state"] = "succeeded" if succeeded else "failed"
        task["updated_at"] = datetime.now(timezone.utc).isoformat()
        task["execution_result"] = execution_result
        task["commit_ref"] = None
        self._append_task_note(
            task, "Execution completed" if succeeded else "Execution failed")
        if note:
            self._append_task_note(task, f"Approval note: {note}")
        self._logger.info(
            "event=remediation_execution_done ms=%d task_id=%s success=%s",
            int((time.perf_counter() - t_task) * 1000),
            task.get("task_id"),
            str(succeeded).lower(),
        )
        return task

    def create_task(self, request: RemediationRequest, runbook: RunbookDefinition) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        task_id = str(uuid4())
        branch = f"auto/hephaestus/{task_id[:8]}"
        task = {
            "task_id": task_id,
            "incident_id": request.incident_id,
            "source": request.source,
            "service": request.service,
            "issue": request.issue,
            "severity": request.severity.lower(),
            "environment": request.environment.lower(),
            "requested_action": request.requested_action,
            "runbook_id": runbook.runbook_id,
            "state": "pending_approval",
            "dry_run": bool(request.dry_run),
            "auto_approve": bool(request.auto_approve),
            "created_at": now,
            "updated_at": now,
            "branch": branch,
            "baseline_ref": self._baseline_ref,
            "commit_ref": None,
            "rollback_ref": self._baseline_ref,
            "notifications": [],
            "attempts": 1,
            "metadata": request.metadata,
        }

        self._logger.info(
            "event=remediation_task_created task_id=%s service=%s issue=%s state=%s",
            task_id,
            request.service,
            request.issue,
            task["state"],
        )

        if self._approval_required(request):
            task["state"] = "pending_approval"
            self._append_task_note(
                task, "Mutation requires explicit approval by policy")
        elif request.auto_approve and not request.dry_run and not self._allow_auto_approve_non_prod:
            task["state"] = "pending_approval"
            self._append_task_note(
                task, "Auto-approve blocked by policy for non-production mutation")
        else:
            task = self._execute_task(
                task,
                approved_by="policy:auto" if request.auto_approve else "policy:direct",
            )

        with self._tasks_lock:
            self._tasks[task_id] = task
        self._agenda_sync(task)

        self._notify_change(
            event_type="remediation.created",
            task=task,
            message=(
                f"Hephaestus remediation task created for {request.service} "
                f"(task={task['task_id']}, state={task['state']}, branch={task['branch']})."
            ),
        )
        return task

    def list_tasks(self, limit: int = 100, state: str | None = None) -> list[dict[str, Any]]:
        with self._tasks_lock:
            rows = list(self._tasks.values())
        if state:
            rows = [row for row in rows if str(
                row.get("state") or "") == state]
        rows.sort(key=lambda item: str(
            item.get("created_at") or ""), reverse=True)
        return rows[: max(1, min(limit, 500))]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._tasks_lock:
            return self._tasks.get(task_id)

    def approve_task(self, task_id: str, request: RemediationApproveRequest) -> dict[str, Any] | None:
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if request.dry_run_override is not None:
                task["dry_run"] = bool(request.dry_run_override)
            if str(task.get("state") or "") in {"succeeded", "rolled_back"}:
                return task
            task = self._execute_task(
                task, approved_by=request.approved_by, note=request.note)
            self._tasks[task_id] = task
        self._agenda_sync(task)

        self._notify_change(
            event_type="remediation.executed" if str(
                task.get("state")) == "succeeded" else "remediation.failed",
            task=task,
            message=(
                f"Hephaestus remediation execution result for task={task_id} "
                f"state={task.get('state')} rollback_ref={task.get('rollback_ref')}"
            ),
        )
        return task

    def rollback_task(self, task_id: str, request: RemediationRollbackRequest) -> dict[str, Any] | None:
        t_rollback = time.perf_counter()
        with self._tasks_lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task["state"] = "rolled_back"
            task["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._append_task_note(
                task, f"Rollback requested by {request.requested_by}: {request.reason}")
            self._tasks[task_id] = task
        self._agenda_sync(task)

        self._notify_change(
            event_type="remediation.rolled_back",
            task=task,
            message=(
                f"Hephaestus rollback executed for task={task_id} "
                f"to rollback_ref={task.get('rollback_ref')}"
            ),
        )
        self._logger.info(
            "event=remediation_rollback_done ms=%d task_id=%s",
            int((time.perf_counter() - t_rollback) * 1000),
            task_id,
        )
        return task
