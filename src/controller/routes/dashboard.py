"""Dashboard stats and recent error logs."""

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.controller.auth import require_auth
from src.shared.database import get_db
from src.shared.models import ApiKey, OdooConnection, RequestLog

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(db: Session = Depends(get_db), _: str = Depends(require_auth)):
    total_requests = db.execute(select(func.count(RequestLog.id))).scalar_one()
    total_errors = db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.status == "error")
    ).scalar_one()
    active_connections = db.execute(
        select(func.count(OdooConnection.id)).where(OdooConnection.is_active == True)  # noqa: E712
    ).scalar_one()
    active_keys = db.execute(
        select(func.count(ApiKey.id)).where(ApiKey.is_active == True)  # noqa: E712
    ).scalar_one()

    # Per-tool breakdown
    tool_rows = db.execute(
        select(RequestLog.tool_name, func.count(RequestLog.id).label("count"))
        .group_by(RequestLog.tool_name)
        .order_by(func.count(RequestLog.id).desc())
    ).all()
    tool_stats = [{"tool": r.tool_name, "count": r.count} for r in tool_rows]

    # Recent 50 logs (newest first)
    recent = db.execute(
        select(RequestLog).order_by(RequestLog.timestamp.desc()).limit(50)
    ).scalars().all()
    recent_logs = [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
            "tool_name": r.tool_name,
            "status": r.status,
            "duration_ms": r.duration_ms,
            "error_message": r.error_message,
        }
        for r in recent
    ]

    return {
        "total_requests": total_requests,
        "total_errors": total_errors,
        "active_connections": active_connections,
        "active_keys": active_keys,
        "tool_stats": tool_stats,
        "recent_logs": recent_logs,
    }
