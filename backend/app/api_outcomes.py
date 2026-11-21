"""Outcome tracking API: a user's due predictions, and the admin backtest.

Recording an outcome reuses POST /api/predictions/{id}/outcome (main.py).
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .auth import current_user
from .astro import backtest
from .db import BirthProfile, PredictionRecord, User, get_db

router = APIRouter()


@router.get("/api/predictions/due")
def due_predictions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Issued forecasts (all of the user's profiles) whose window has ended and have no outcome yet."""
    recs = (db.query(PredictionRecord).join(BirthProfile, PredictionRecord.profile_id == BirthProfile.id)
            .filter(BirthProfile.user_id == user.id, PredictionRecord.forecast == "event_indicated",
                    PredictionRecord.outcome.is_(None), PredictionRecord.window_end < date.today())
            .order_by(PredictionRecord.window_end, PredictionRecord.id).all())
    return {"due": [_row(r) for r in recs], "count": len(recs)}


@router.get("/api/predictions/history")
def answered_predictions(limit: int = Query(default=50, ge=1, le=200), user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    """Predictions that already have a recorded outcome (newest first)."""
    recs = (db.query(PredictionRecord).join(BirthProfile, PredictionRecord.profile_id == BirthProfile.id)
            .filter(BirthProfile.user_id == user.id, PredictionRecord.outcome.isnot(None))
            .order_by(PredictionRecord.outcome_at.desc()).limit(limit).all())
    return {"answered": [_row(r) for r in recs]}


def _row(r: PredictionRecord) -> dict:
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    return {"id": r.id, "domain": r.domain, "event_type": r.event_type, "question": r.question,
            "success_criteria": r.success_criteria, "window_start": iso(r.window_start),
            "window_end": iso(r.window_end), "outcome": r.outcome, "event_date": iso(r.event_date),
            "registered": r.registration is not None}


def _require_admin(user: User = Depends(current_user)) -> User:
    from . import main          # lazy: main includes this router
    if not main._is_admin(user):
        raise HTTPException(403, "not authorised")
    return user


@router.get("/api/admin/backtest")
def admin_backtest(refresh: bool = Query(default=False), admin: User = Depends(_require_admin),
                   db: Session = Depends(get_db)):
    """Latest stored backtest report; with refresh=true (or none stored) recompute from the
    recorded outcomes and, when refreshed, write backend/data/backtest_report.{json,md}."""
    report = None if refresh else backtest.load_report()
    if report is None:
        rows, excluded = backtest.rows_from_db(db)
        report = backtest.build_report(rows, exclusions=excluded)
        if refresh:
            backtest.write_report(report)
    return report
