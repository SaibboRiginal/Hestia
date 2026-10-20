"""LLM usage storage — one row per LLM call made by Oracle (docs/work/2026-10-19-oracle-a-blocchi §E).

Archive only stores and sums: what a module, a chain or a cost means lives in Hestia-Oracle, the only caller
(``/api/llm/usage``). Oracle sends its retention with every write; older rows are removed then (no timer).
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .. import models, database

router = APIRouter(prefix="/api/llm-usage-store", tags=["llm-usage"])

_MAX_ROWS = 500
_GROUPS = {
    "module": (models.LLMUsage.module,),
    "session": (models.LLMUsage.session_id, models.LLMUsage.client),
    "usecase": (models.LLMUsage.use_case, models.LLMUsage.chain),
    "model": (models.LLMUsage.provider, models.LLMUsage.model),
    "step": (models.LLMUsage.use_case, models.LLMUsage.chain, models.LLMUsage.step, models.LLMUsage.provider,
             models.LLMUsage.model),
    "day": (func.date(models.LLMUsage.at),),
}
_NAMES = {"module": ["module"], "session": ["session_id", "client"], "usecase": ["use_case", "chain"],
          "model": ["provider", "model"], "step": ["use_case", "chain", "step", "provider", "model"], "day": ["day"]}


class UsageRow(BaseModel):
    at: datetime
    module: str = Field(..., min_length=1, max_length=80)
    use_case: str = Field(..., min_length=1, max_length=120)
    chain: Optional[str] = Field(None, max_length=80)
    step: int = 0
    provider: Optional[str] = Field(None, max_length=80)
    model: Optional[str] = Field(None, max_length=160)
    client: Optional[str] = Field(None, max_length=80)
    session_id: Optional[str] = Field(None, max_length=120)
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    context_window: int = 0
    duration_ms: int = 0
    cost_usd: float = 0.0
    cost_kind: Optional[str] = Field(None, max_length=20)
    outcome: str = Field("ok", max_length=20)
    detail: Optional[str] = Field(None, max_length=300)


class UsageWrite(BaseModel):
    rows: List[UsageRow]
    retention_days: int = Field(90, ge=1, le=3650)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


@router.post("/rows")
def write_rows(req: UsageWrite, db: Session = Depends(database.get_db)) -> dict:
    if len(req.rows) > _MAX_ROWS:
        raise HTTPException(status_code=413, detail=f"max {_MAX_ROWS} rows per write")
    for r in req.rows:
        db.add(models.LLMUsage(**{**r.model_dump(), "at": _utc(r.at)}))
    cutoff = datetime.now(timezone.utc) - timedelta(days=req.retention_days)
    removed = db.query(models.LLMUsage).filter(models.LLMUsage.at < cutoff).delete(synchronize_session=False)
    db.commit()
    return {"status": "ok", "written": len(req.rows), "removed": int(removed or 0)}


def _filtered(db: Session, days: int, module: str, session_id: str, use_case: str):
    q = db.query(models.LLMUsage).filter(models.LLMUsage.at >= datetime.now(timezone.utc) - timedelta(days=days))
    if module:
        q = q.filter(models.LLMUsage.module == module)
    if session_id:
        q = q.filter(models.LLMUsage.session_id == session_id)
    if use_case:
        q = q.filter(models.LLMUsage.use_case == use_case)
    return q


@router.get("/summary")
def summary(group: str = "module", days: int = Query(7, ge=1, le=3650), module: str = "", session_id: str = "",
            use_case: str = "", limit: int = Query(200, ge=1, le=2000),
            db: Session = Depends(database.get_db)) -> dict:
    """Totals grouped by module | session | usecase | model | step | day over the last *days*."""
    if group not in _GROUPS:
        raise HTTPException(status_code=400, detail=f"group must be one of {sorted(_GROUPS)}")
    U = models.LLMUsage
    keys = _GROUPS[group]
    ok = case((U.outcome == "ok", 1), else_=0)
    cols = [*keys, func.count(U.id), func.sum(ok), func.sum(case((U.outcome == "quota", 1), else_=0)),
            func.sum(case(((U.outcome == "ok") & (U.step > 0), 1), else_=0)),
            func.sum(U.input_tokens), func.sum(U.cached_tokens), func.sum(U.output_tokens), func.sum(U.cost_usd),
            func.sum(U.duration_ms), func.max(U.input_tokens), func.max(U.context_window), func.min(U.at),
            func.max(U.at)]
    q = _filtered(db, days, module, session_id, use_case).with_entities(*cols).group_by(*keys)
    rows = []
    for rec in q.order_by(func.count(U.id).desc()).limit(limit).all():
        vals = list(rec)
        head, (calls, oks, quota, fallback, inp, cached, out, cost, dur, max_in, window, first, last) = \
            vals[:len(keys)], vals[len(keys):]
        row = dict(zip(_NAMES[group], [str(v) if group == "day" else v for v in head]))
        calls = int(calls or 0)
        row.update(calls=calls, ok=int(oks or 0), errors=calls - int(oks or 0), quota=int(quota or 0),
                   fallbacks=int(fallback or 0), input_tokens=int(inp or 0), cached_tokens=int(cached or 0),
                   output_tokens=int(out or 0), cost_usd=round(float(cost or 0), 6),
                   avg_duration_ms=round(int(dur or 0) / calls) if calls else 0, max_input_tokens=int(max_in or 0),
                   context_window=int(window or 0), first_at=_iso(first), last_at=_iso(last))
        rows.append(row)
    if group == "day":
        rows.sort(key=lambda r: r["day"])
    return {"group": group, "days": days, "rows": rows}


@router.get("/rows")
def list_rows(days: int = Query(7, ge=1, le=3650), module: str = "", session_id: str = "", use_case: str = "",
              limit: int = Query(100, ge=1, le=1000), db: Session = Depends(database.get_db)) -> dict:
    """Latest calls (newest first), e.g. the detail of one session."""
    q = _filtered(db, days, module, session_id, use_case).order_by(models.LLMUsage.at.desc()).limit(limit)
    return {"rows": [_view(r) for r in q.all()]}


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return _utc(value).isoformat()


def _view(r: models.LLMUsage) -> dict:
    return {"at": _iso(r.at), "module": r.module, "use_case": r.use_case, "chain": r.chain, "step": r.step,
            "provider": r.provider, "model": r.model, "client": r.client, "session_id": r.session_id,
            "input_tokens": r.input_tokens, "cached_tokens": r.cached_tokens, "output_tokens": r.output_tokens,
            "context_window": r.context_window, "duration_ms": r.duration_ms, "cost_usd": r.cost_usd,
            "cost_kind": r.cost_kind, "outcome": r.outcome, "detail": r.detail}
