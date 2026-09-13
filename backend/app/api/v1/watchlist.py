"""Real-Time Watchlist & Hotlist Matching Engine API Endpoints (Module 18)."""

from typing import List, Optional

from app.db.session import get_db
from app.schemas.common import APIResponse
from app.schemas.watchlist import (
    AlertAcknowledgeRequest,
    AlertResponse,
    BulkWatchlistImportRequest,
    BulkWatchlistImportResponse,
    WatchlistCreate,
    WatchlistEntryCreate,
    WatchlistEntryResponse,
    WatchlistMatchEvaluationRequest,
    WatchlistMatchResult,
    WatchlistResponse,
    WatchlistTelemetry,
)
from app.services.watchlist_service import watchlist_service
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/watchlist", tags=["Real-Time Watchlist & Hotlist Matching Engine"])


@router.post("/evaluate", response_model=APIResponse[WatchlistMatchResult])
async def evaluate_vehicle_against_watchlist(
    payload: WatchlistMatchEvaluationRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[WatchlistMatchResult]:
    """Evaluate detected vehicle plate against active police hotlists in < 50ms with automated Alert dispatch."""
    result = await watchlist_service.evaluate_plate(db, payload)
    msg = (
        f"🚨 HOTLIST HIT! Alert generated (ID: {result.alert_id})"
        if result.is_match
        else "No hotlist match found"
    )
    return APIResponse(data=result, message=msg)


@router.get("", response_model=APIResponse[List[WatchlistResponse]])
async def list_watchlists(
    db: AsyncSession = Depends(get_db),
) -> APIResponse[List[WatchlistResponse]]:
    """List all categorized Watchlist containers."""
    watchlists = await watchlist_service.get_watchlists(db)
    return APIResponse(data=watchlists, message=f"Retrieved {len(watchlists)} watchlists")


@router.post("", response_model=APIResponse[WatchlistResponse], status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    payload: WatchlistCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[WatchlistResponse]:
    """Create a new categorized Watchlist container."""
    watchlist = await watchlist_service.create_watchlist(db, payload)
    return APIResponse(data=watchlist, message="Watchlist created successfully")


@router.post(
    "/entries",
    response_model=APIResponse[WatchlistEntryResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_watchlist_entry(
    payload: WatchlistEntryCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[WatchlistEntryResponse]:
    """Add a target vehicle plate to a watchlist and immediately update in-memory cache."""
    entry = await watchlist_service.create_entry(db, payload)
    return APIResponse(data=entry, message="Watchlist entry added and in-memory cache synchronized")


@router.post("/bulk-import", response_model=APIResponse[BulkWatchlistImportResponse])
async def bulk_import_hotlist(
    payload: BulkWatchlistImportRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[BulkWatchlistImportResponse]:
    """Bulk import hundreds or thousands of police hotlist records into a watchlist."""
    result = await watchlist_service.bulk_import(db, payload)
    return APIResponse(
        data=result,
        message=f"Successfully imported {result.imported_count} hotlist entries into '{payload.watchlist_name}'",
    )


@router.get("/entries", response_model=APIResponse[List[WatchlistEntryResponse]])
async def list_watchlist_entries(
    watchlist_id: Optional[str] = Query(None, description="Optional filter by watchlist UUID"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[List[WatchlistEntryResponse]]:
    """Fetch all active hotlist vehicle plate entries."""
    entries = await watchlist_service.get_entries(db, watchlist_id=watchlist_id)
    return APIResponse(data=entries, message=f"Retrieved {len(entries)} watchlist entries")


@router.get("/alerts", response_model=APIResponse[List[AlertResponse]])
async def list_hotlist_alerts(
    limit: int = Query(50, ge=1, le=200, description="Max alerts to return"),
    status_filter: Optional[str] = Query(
        None, description="NEW, ACKNOWLEDGED, RESOLVED, DISMISSED"
    ),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[List[AlertResponse]]:
    """Fetch recent hotlist alerts dispatched to the command center."""
    alerts = await watchlist_service.get_alerts(db, limit=limit, status_filter=status_filter)
    return APIResponse(data=alerts, message=f"Retrieved {len(alerts)} alerts")


@router.put("/alerts/{alert_id}/acknowledge", response_model=APIResponse[AlertResponse])
async def acknowledge_alert(
    alert_id: str,
    payload: AlertAcknowledgeRequest,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[AlertResponse]:
    """Operator action to acknowledge, resolve, or dismiss a dispatched alert with audit notes."""
    alert = await watchlist_service.acknowledge_alert(db, alert_id, payload)
    if not alert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Alert with ID '{alert_id}' not found",
        )
    return APIResponse(data=alert, message=f"Alert status updated to '{payload.status}'")


@router.get("/telemetry", response_model=APIResponse[WatchlistTelemetry])
async def get_watchlist_telemetry() -> APIResponse[WatchlistTelemetry]:
    """Retrieve real-time watchlist matching throughput, hit rate, and sub-50ms latency compliance."""
    telemetry = watchlist_service.get_telemetry()
    return APIResponse(data=telemetry, message="Watchlist telemetry retrieved")
