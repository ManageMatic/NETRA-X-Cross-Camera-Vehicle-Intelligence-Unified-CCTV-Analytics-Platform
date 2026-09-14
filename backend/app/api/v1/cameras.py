"""Camera Registry, Live Streaming, Health Telemetry, and Testing Endpoints."""

import math
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ResourceNotFoundException
from app.db.session import get_db
from app.integrations.sentinel.client import sentinel_client
from app.integrations.sentinel.rtsp import validate_camera_id
from app.models.camera import Camera, CameraHealth, CameraSource
from app.schemas.camera import (
    CameraCreate,
    CameraDetailResponse,
    CameraHealthLiveResponse,
    CameraHealthResponse,
    CameraResponse,
    CameraSourceResponse,
    CameraSyncResult,
    CameraTestResult,
    CameraUpdate,
)
from app.schemas.common import APIResponse, PaginatedResponse, PaginationMetadata
from app.services.camera_catalog import catalog_service
from app.video.stream_manager import video_stream_manager

router = APIRouter(prefix="/cameras", tags=["Camera Registry & Ingestion"])


@router.get(
    "",
    response_model=PaginatedResponse[CameraResponse],
    summary="List all registered cameras with filtering and pagination",
)
async def list_cameras(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    live_status: Optional[bool] = Query(None, description="Filter by online/offline status"),
    department: Optional[str] = Query(None, description="Filter by police department"),
    search: Optional[str] = Query(None, description="Search by camera name, ID, or location"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all ingested CCTV cameras."""
    query = select(Camera)
    count_query = select(func.count(Camera.id))

    if live_status is not None:
        query = query.where(Camera.live_status == live_status)
        count_query = count_query.where(Camera.live_status == live_status)

    if department:
        query = query.where(Camera.department.ilike(f"%{department}%"))
        count_query = count_query.where(Camera.department.ilike(f"%{department}%"))

    if search:
        search_filter = (
            Camera.name.ilike(f"%{search}%")
            | Camera.external_camera_id.ilike(f"%{search}%")
            | Camera.location_name.ilike(f"%{search}%")
        )
        query = query.where(search_filter)
        count_query = count_query.where(search_filter)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    offset = (page - 1) * page_size
    query = query.order_by(Camera.created_at.asc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    cameras = result.scalars().all()

    camera_responses = [CameraResponse.model_validate(c) for c in cameras]
    total_pages = math.ceil(total / page_size) if total > 0 else 0

    pagination = PaginationMetadata(
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=total_pages,
        has_next=page < total_pages,
        has_prev=page > 1,
    )

    return PaginatedResponse(
        success=True,
        message="Cameras retrieved successfully",
        data=camera_responses,
        pagination=pagination,
    )


@router.post(
    "/sync",
    response_model=APIResponse[CameraSyncResult],
    summary="Trigger dynamic discovery sync from Sentinel /api/ingest",
)
async def sync_catalog(
    catalog_url: Optional[str] = Query(
        None, description="Optional override URL for camera catalog ingestion"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Synchronize camera feeds dynamically from Gujarat Police Sentinel Sandbox without hardcoding."""
    sync_result = await catalog_service.sync_catalog_to_db(db=db, catalog_url=catalog_url)
    return APIResponse(
        success=True,
        message="Dynamic camera catalog synchronization complete",
        data=sync_result,
    )


@router.get(
    "/{camera_id}",
    response_model=APIResponse[CameraDetailResponse],
    summary="Get single camera with stream sources and health telemetry",
)
async def get_camera_detail(
    camera_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve camera metadata and active stream endpoints by internal UUID or external_camera_id."""
    clean_id = camera_id.strip()
    stmt = select(Camera).where(
        (Camera.id == clean_id)
        | (Camera.external_camera_id == clean_id)
        | (Camera.external_camera_id.ilike(clean_id))
    )
    result = await db.execute(stmt)
    camera = result.scalar_one_or_none()

    if not camera:
        raise ResourceNotFoundException("Camera", camera_id)

    # Get latest health metric
    health_stmt = (
        select(CameraHealth)
        .where(CameraHealth.camera_id == camera.id)
        .order_by(CameraHealth.created_at.desc())
        .limit(1)
    )
    health_result = await db.execute(health_stmt)
    latest_health = health_result.scalar_one_or_none()

    detail = CameraDetailResponse(
        id=camera.id,
        external_camera_id=camera.external_camera_id,
        name=camera.name,
        location_name=camera.location_name,
        department=camera.department,
        latitude=camera.latitude,
        longitude=camera.longitude,
        vendor=camera.vendor,
        vms=camera.vms,
        protocol=camera.protocol,
        codec=camera.codec,
        width=camera.width,
        height=camera.height,
        fps=camera.fps,
        whep_url=camera.whep_url,
        hls_url=camera.hls_url,
        live_status=camera.live_status,
        is_active_for_ai=camera.is_active_for_ai,
        last_seen=camera.last_seen,
        created_at=camera.created_at,
        updated_at=camera.updated_at,
        sources=[CameraSourceResponse.model_validate(s) for s in camera.sources],
        latest_health=(
            CameraHealthResponse.model_validate(latest_health) if latest_health else None
        ),
    )

    return APIResponse(
        success=True,
        message="Camera details retrieved successfully",
        data=detail,
    )


@router.get(
    "/{camera_id}/health",
    response_model=APIResponse[CameraHealthLiveResponse],
    summary="Get real-time health and telemetry metrics for a camera",
)
async def get_camera_health(camera_id: str):
    """Retrieve live FPS, latency, reconnect counts, and decode errors for an active camera."""
    valid_id = validate_camera_id(camera_id)
    health_data = video_stream_manager.get_camera_health(valid_id)
    return APIResponse(
        success=True,
        message="Camera health telemetry retrieved",
        data=CameraHealthLiveResponse(**health_data),
    )


@router.post(
    "/{camera_id}/test",
    response_model=APIResponse[CameraTestResult],
    summary="Test authenticated RTSP connectivity and first frame grab",
)
async def test_camera_connection(camera_id: str):
    """Probes RTSP stream over TCP, extracts basic frame metadata, and verifies reachability."""
    valid_id = validate_camera_id(camera_id)
    test_result = await sentinel_client.test_camera(valid_id, timeout_seconds=5.0)
    return APIResponse(
        success=True,
        message="Camera connection test completed",
        data=CameraTestResult(**test_result),
    )


@router.get(
    "/{camera_id}/snapshot",
    summary="Get real-time live JPEG image snapshot from camera feed",
    responses={200: {"content": {"image/jpeg": {}}}},
)
async def get_camera_snapshot_direct(camera_id: str):
    """Retrieve binary JPEG image snapshot directly from video stream session."""
    valid_id = validate_camera_id(camera_id)
    session = video_stream_manager.get_or_create_session(valid_id)
    jpeg = session.get_latest_jpeg()
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get(
    "/{camera_id}/preview",
    summary="Get live JPEG snapshot preview of camera feed",
)
async def get_camera_preview(camera_id: str):
    """Returns a single decoded JPEG snapshot with image/jpeg header."""
    valid_id = validate_camera_id(camera_id)

    # 1. Check active session cached frame or initialize
    session = video_stream_manager.get_or_create_session(valid_id)
    if session:
        jpeg = session.get_latest_jpeg()
        if jpeg:
            return Response(
                content=jpeg,
                media_type="image/jpeg",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )

    # 2. Try on-demand snapshot grab from RTSP
    jpeg = await sentinel_client.fetch_snapshot(valid_id)
    if jpeg:
        return Response(
            content=jpeg,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    # 3. Fallback 1x1 transparent or placeholder JPEG
    # Minimal 1x1 black JPEG header bytes
    placeholder = (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00H\x00H\x00\x00\xff\xdb\x00C\x00\x08\x06"
        b"\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f"
        b"\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\xff\xc0"
        b"\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01"
        b"\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t"
        b"\n\x0b\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xbf\x00\xff\xd9"
    )
    return Response(content=placeholder, media_type="image/jpeg")


@router.get(
    "/{camera_id}/stream",
    summary="Direct low-latency live video stream for browser playback",
)
async def get_live_camera_stream(camera_id: str):
    """Provides a continuous low-latency multipart/x-mixed-replace JPEG video stream."""
    from fastapi.responses import StreamingResponse

    valid_id = validate_camera_id(camera_id)
    session = video_stream_manager.get_or_create_session(valid_id)
    return StreamingResponse(
        session.mjpeg_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post(
    "/{camera_id}/whep",
    summary="WebRTC WHEP SDP signaling proxy",
)
async def proxy_whep_signaling(camera_id: str, request: Request):
    """Proxies WebRTC SDP offer from browser to Sentinel MediaMTX gateway with authentication."""
    import httpx
    import urllib.parse
    from app.core.config import get_settings

    valid_id = validate_camera_id(camera_id)
    sdp_body = (await request.body()).decode("utf-8")
    settings = get_settings()

    user = urllib.parse.quote(settings.effective_sentinel_username or "")
    code = urllib.parse.quote(settings.SENTINEL_ACCESS_CODE or "")
    target_url = (
        f"http://{user}:{code}@{settings.SENTINEL_DIRECT_IP}:{settings.SENTINEL_WHEP_PORT}/stream/{valid_id}/whep"
        if user and code
        else f"http://{settings.SENTINEL_DIRECT_IP}:{settings.SENTINEL_WHEP_PORT}/stream/{valid_id}/whep"
    )

    timeout = httpx.Timeout(4.0, connect=2.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                target_url,
                content=sdp_body,
                headers={"Content-Type": "application/sdp"},
            )
            return Response(content=resp.text, status_code=resp.status_code, media_type="application/sdp")
        except Exception as e:
            return Response(
                content=f"v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\nc=IN IP4 0.0.0.0\r\na=rtpmap:96 H264/90000\r\n",
                media_type="application/sdp",
                status_code=200,
            )


@router.post(
    "/{camera_id}/reconnect",
    response_model=APIResponse[dict],
    summary="Force reconnect stream session for camera",
)
async def reconnect_camera(camera_id: str):
    """Stops and restarts stream session for specified camera."""
    valid_id = validate_camera_id(camera_id)
    video_stream_manager.stop_session(valid_id)
    session = video_stream_manager.get_or_create_session(valid_id)
    return APIResponse(
        success=True,
        message=f"Reconnection triggered for camera {valid_id}",
        data={"camera_id": valid_id, "state": session.state.value if hasattr(session.state, "value") else str(session.state)},
    )


@router.post(
    "",
    response_model=APIResponse[CameraResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Manually register a new camera feed",
)
async def create_camera(
    payload: CameraCreate,
    db: AsyncSession = Depends(get_db),
):
    """Manually onboard a CCTV camera feed into the registry."""
    stmt = select(Camera).where(Camera.external_camera_id == payload.external_camera_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise ValueError(f"Camera with ID '{payload.external_camera_id}' already registered.")

    camera = Camera(**payload.model_dump())
    db.add(camera)
    await db.flush()

    source = CameraSource(
        camera_id=camera.id,
        stream_type="MAIN",
        url=payload.rtsp_url,
        codec=payload.codec,
        resolution=f"{payload.width}x{payload.height}",
    )
    db.add(source)
    await db.commit()
    await db.refresh(camera)

    return APIResponse(
        success=True,
        message="Camera registered successfully",
        data=CameraResponse.model_validate(camera),
    )


@router.patch(
    "/{camera_id}",
    response_model=APIResponse[CameraResponse],
    summary="Update camera settings or status",
)
async def update_camera(
    camera_id: str,
    payload: CameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update camera configuration, AI activation flag, or coordinates."""
    clean_id = camera_id.strip()
    stmt = select(Camera).where(
        (Camera.id == clean_id)
        | (Camera.external_camera_id == clean_id)
        | (Camera.external_camera_id.ilike(clean_id))
    )
    result = await db.execute(stmt)
    camera = result.scalar_one_or_none()

    if not camera:
        raise ResourceNotFoundException("Camera", camera_id)

    update_data = payload.model_dump(exclude_unset=True)
    for key, val in update_data.items():
        setattr(camera, key, val)

    await db.commit()
    await db.refresh(camera)

    return APIResponse(
        success=True,
        message="Camera updated successfully",
        data=CameraResponse.model_validate(camera),
    )
