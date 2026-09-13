"""Vehicle Event Ingestion & Indexer API Endpoints (Module 14)."""

from typing import List, Optional

from app.db.session import get_db
from app.models.vehicle import VehicleEvent
from app.schemas.common import APIResponse
from app.schemas.events import (
    EventIndexerTelemetry,
    RecentEventsFilter,
    VehicleEventBatchCreate,
    VehicleEventCreate,
    VehicleEventResponse,
    VehiclePlateResponse,
)
from app.services.event_indexer import event_indexer
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/events", tags=["Vehicle Event Ingestion & Indexer"])


@router.post(
    "/ingest", response_model=APIResponse[VehicleEventResponse], status_code=status.HTTP_201_CREATED
)
async def ingest_vehicle_event(
    payload: VehicleEventCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VehicleEventResponse]:
    """Ingest a single vehicle intelligence event with plate, embedding, and snapshot evidence."""
    event = await event_indexer.ingest_event(db, payload)
    return APIResponse(data=event, message="Vehicle event ingested and indexed successfully")


@router.post(
    "/batch-ingest",
    response_model=APIResponse[List[VehicleEventResponse]],
    status_code=status.HTTP_201_CREATED,
)
async def ingest_vehicle_event_batch(
    payload: VehicleEventBatchCreate,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[List[VehicleEventResponse]]:
    """Batch ingest multiple vehicle intelligence events in an optimized transaction."""
    events = await event_indexer.ingest_batch(db, payload)
    return APIResponse(data=events, message=f"Successfully ingested {len(events)} vehicle events")


@router.get("/recent", response_model=APIResponse[List[VehicleEventResponse]])
async def get_recent_indexed_events(
    camera_id: Optional[str] = Query(None, description="Filter by camera UUID"),
    vehicle_class: Optional[str] = Query(
        None, description="Filter by vehicle class (car, bus, etc.)"
    ),
    plate_query: Optional[str] = Query(None, description="Partial or exact license plate query"),
    limit: int = Query(50, ge=1, le=500, description="Max number of events to return"),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[List[VehicleEventResponse]]:
    """Retrieve real-time recent vehicle events from ring buffer with database fallback."""
    filters = RecentEventsFilter(
        camera_id=camera_id,
        vehicle_class=vehicle_class,
        plate_query=plate_query,
        limit=limit,
    )
    events = event_indexer.get_recent_events(filters)
    if len(events) < limit:
        existing_ids = {e.id for e in events}
        stmt = select(VehicleEvent).order_by(VehicleEvent.event_time.desc()).limit(limit)
        if camera_id:
            stmt = stmt.where(VehicleEvent.camera_id == camera_id)
        if vehicle_class:
            stmt = stmt.where(VehicleEvent.vehicle_class == vehicle_class)
        result = await db.execute(stmt)
        db_events = result.scalars().all()
        for ev in db_events:
            if ev.id in existing_ids:
                continue
            if plate_query:
                q = plate_query.upper().replace(" ", "")
                p_norm = (ev.plate_normalized or "").upper().replace(" ", "")
                p_raw = (ev.plate_raw or "").upper().replace(" ", "")
                if q not in p_norm and q not in p_raw:
                    continue
            plates_list = [
                VehiclePlateResponse(
                    id=p.id,
                    plate_text=p.plate_text,
                    plate_normalized=p.plate_normalized,
                    confidence=p.confidence,
                    crop_path=p.crop_path,
                )
                for p in ev.plates
            ]
            events.append(
                VehicleEventResponse(
                    id=ev.id,
                    camera_id=ev.camera_id,
                    track_id=ev.track_id,
                    event_time=ev.event_time,
                    source_pts=ev.source_pts,
                    plate_raw=ev.plate_raw,
                    plate_normalized=ev.plate_normalized,
                    plate_confidence=ev.plate_confidence,
                    vehicle_class=ev.vehicle_class,
                    vehicle_color=ev.vehicle_color,
                    detection_confidence=ev.detection_confidence,
                    latitude=ev.latitude,
                    longitude=ev.longitude,
                    location_name=ev.location_name,
                    bbox_x1=ev.bbox_x1,
                    bbox_y1=ev.bbox_y1,
                    bbox_x2=ev.bbox_x2,
                    bbox_y2=ev.bbox_y2,
                    snapshot_path=ev.snapshot_path,
                    plates=plates_list,
                    has_embedding=ev.embedding is not None,
                    created_at=ev.created_at,
                )
            )
            if len(events) >= limit:
                break

    return APIResponse(data=events, message=f"Retrieved {len(events)} recent vehicle events")


@router.get("/telemetry", response_model=APIResponse[EventIndexerTelemetry])
async def get_event_indexer_telemetry() -> APIResponse[EventIndexerTelemetry]:
    """Retrieve real-time event ingestion throughput, EPS, latency, and storage metrics."""
    telemetry = event_indexer.get_telemetry()
    return APIResponse(data=telemetry, message="Event indexer telemetry retrieved")


@router.get("/{event_id}", response_model=APIResponse[VehicleEventResponse])
async def get_event_by_id(
    event_id: str,
    db: AsyncSession = Depends(get_db),
) -> APIResponse[VehicleEventResponse]:
    """Fetch complete indexed vehicle event details from database by UUID."""
    stmt = select(VehicleEvent).where(VehicleEvent.id == event_id)
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vehicle event with ID '{event_id}' not found",
        )

    plates_list = [
        VehiclePlateResponse(
            id=p.id,
            plate_text=p.plate_text,
            plate_normalized=p.plate_normalized,
            confidence=p.confidence,
            crop_path=p.crop_path,
        )
        for p in event.plates
    ]

    response_data = VehicleEventResponse(
        id=event.id,
        camera_id=event.camera_id,
        track_id=event.track_id,
        event_time=event.event_time,
        source_pts=event.source_pts,
        plate_raw=event.plate_raw,
        plate_normalized=event.plate_normalized,
        plate_confidence=event.plate_confidence,
        vehicle_class=event.vehicle_class,
        vehicle_color=event.vehicle_color,
        detection_confidence=event.detection_confidence,
        latitude=event.latitude,
        longitude=event.longitude,
        location_name=event.location_name,
        bbox_x1=event.bbox_x1,
        bbox_y1=event.bbox_y1,
        bbox_x2=event.bbox_x2,
        bbox_y2=event.bbox_y2,
        snapshot_path=event.snapshot_path,
        plates=plates_list,
        has_embedding=event.embedding is not None,
        created_at=event.created_at,
    )

    return APIResponse(data=response_data, message="Vehicle event retrieved successfully")
