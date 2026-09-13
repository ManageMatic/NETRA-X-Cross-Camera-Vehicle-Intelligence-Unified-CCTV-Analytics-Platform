"""Real-Time Watchlist & Hotlist Matching Engine Service (Module 18).

Maintains sub-millisecond in-memory hash indices of police hotlists, evaluates incoming
ANPR plate readings, and automatically generates prioritized Alert records.
"""

import fnmatch
import logging
import re
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Pattern, Tuple

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertEvent, AlertStatus
from app.models.watchlist import Watchlist, WatchlistEntry
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
from app.services.search_engine import levenshtein_distance

logger = logging.getLogger("sentinelx.watchlist")


class WatchlistMatchingEngine:
    """High-Speed In-Memory Police Hotlist & Watchlist Matching Engine."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._is_initialized = False

        # In-memory exact lookup cache: {normalized_plate: entry_dict}
        self._exact_cache: Dict[str, Dict[str, Any]] = {}
        # In-memory wildcard patterns: [(regex_pattern, entry_dict)]
        self._wildcard_cache: List[Tuple[Pattern, Dict[str, Any]]] = []

        # Telemetry
        self._total_evaluations: int = 0
        self._total_hits: int = 0
        self._latency_samples: deque[float] = deque(maxlen=500)
        self._last_evaluation_at: Optional[datetime] = None

    async def sync_cache(self, db: AsyncSession) -> None:
        """Synchronize active database watchlist entries into the high-speed in-memory hash cache."""
        stmt = (
            select(WatchlistEntry)
            .join(Watchlist, WatchlistEntry.watchlist_id == Watchlist.id)
            .where(WatchlistEntry.is_active == True, Watchlist.is_active == True)  # noqa: E712
        )
        res = await db.execute(stmt)
        entries = res.scalars().all()

        new_exact: Dict[str, Dict[str, Any]] = {}
        new_wildcards: List[Tuple[Pattern, Dict[str, Any]]] = []

        for e in entries:
            norm = (
                (e.registration_normalized or e.registration_number)
                .strip()
                .upper()
                .replace(" ", "")
            )
            entry_data = {
                "id": e.id,
                "watchlist_id": e.watchlist_id,
                "registration_number": e.registration_number,
                "registration_normalized": norm,
                "category": e.category,
                "priority": e.priority,
                "notes": e.notes,
            }

            if "*" in norm or "?" in norm:
                regex_str = fnmatch.translate(norm)
                try:
                    pat = re.compile(regex_str, re.IGNORECASE)
                    new_wildcards.append((pat, entry_data))
                except Exception:
                    pass
            else:
                new_exact[norm] = entry_data

        with self._lock:
            self._exact_cache = new_exact
            self._wildcard_cache = new_wildcards
            self._is_initialized = True

        logger.info(
            f"Watchlist cache synchronized: {len(new_exact)} exact, {len(new_wildcards)} wildcard rules."
        )

    async def evaluate_plate(
        self, db: AsyncSession, req: WatchlistMatchEvaluationRequest
    ) -> WatchlistMatchResult:
        """Evaluate an observed license plate against in-memory hotlist in sub-millisecond time."""
        start_t = time.perf_counter()
        now_utc = datetime.now(timezone.utc)

        # Lazy initialize if needed
        if not self._is_initialized:
            await self.sync_cache(db)

        clean_plate = req.plate.strip().upper().replace(" ", "")

        matched_entry: Optional[Dict[str, Any]] = None
        match_type: Optional[str] = None

        with self._lock:
            # 1. O(1) Exact Hash Lookup
            if clean_plate in self._exact_cache:
                matched_entry = self._exact_cache[clean_plate]
                match_type = "EXACT"

            # 2. Wildcard Pattern Scan
            if not matched_entry and self._wildcard_cache:
                for pat, entry in self._wildcard_cache:
                    if pat.match(clean_plate):
                        matched_entry = entry
                        match_type = "WILDCARD"
                        break

            # 3. Fuzzy Levenshtein Distance 1 (Optical Confusion Tolerance)
            if not matched_entry and len(clean_plate) >= 6:
                for target_norm, entry in self._exact_cache.items():
                    if len(target_norm) == len(clean_plate):
                        if levenshtein_distance(clean_plate, target_norm) <= 1:
                            matched_entry = entry
                            match_type = "FUZZY"
                            break

        # If Match Found, Generate Alert in Database
        alert_id = None
        alert_generated = False

        if matched_entry:
            alert_id = uuid.uuid4().hex
            # Create or resolve event_id
            ev_id = req.event_id or alert_id

            db_alert = Alert(
                id=alert_id,
                vehicle_event_id=ev_id,
                watchlist_entry_id=matched_entry["id"],
                camera_id=req.camera_id,
                registration_number=matched_entry["registration_number"],
                category=matched_entry["category"],
                priority=matched_entry["priority"],
                status=AlertStatus.NEW.value,
                alert_time=now_utc,
                confidence=req.confidence,
                location_name=req.location_name or "Camera Checkpoint",
                snapshot_path=req.snapshot_path,
            )
            db.add(db_alert)

            # Create initial audit log event
            audit_ev = AlertEvent(
                id=uuid.uuid4().hex,
                alert_id=alert_id,
                action="DISPATCHED",
                performed_by="SentinelX AI Hotlist Engine",
                notes=f"Automatic {match_type} match against watchlist category '{matched_entry['category']}'",
            )
            db.add(audit_ev)
            await db.commit()
            alert_generated = True

            # Automatic Real-time WebSocket Broadcast (< 500ms SLA)
            try:
                from app.schemas.websocket import AlertBroadcastPayload
                from app.services.alert_dispatcher import alert_dispatcher

                visual_color = (
                    "#ef4444"
                    if matched_entry["priority"] == "CRITICAL"
                    else "#f97316"
                    if matched_entry["priority"] == "HIGH"
                    else "#eab308"
                )

                payload = AlertBroadcastPayload(
                    alert_id=alert_id,
                    registration_number=matched_entry["registration_number"],
                    category=matched_entry["category"],
                    priority=matched_entry["priority"],
                    camera_id=req.camera_id,
                    camera_name=f"Camera {req.camera_id[:8]}",
                    location_name=req.location_name or "Junction Checkpoint",
                    latitude=23.0225,
                    longitude=72.5714,
                    snapshot_path=req.snapshot_path,
                    alert_time=now_utc,
                    audio_alert=matched_entry["priority"] in ["CRITICAL", "HIGH"],
                    visual_color=visual_color,
                    message=f"🚨 HOTLIST HIT: {matched_entry['category']} vehicle {matched_entry['registration_number']} detected!",
                )
                await alert_dispatcher.broadcast_alert(payload)
            except Exception as e:
                logger.warning(f"Failed to broadcast WebSocket alert: {e}")

        elapsed_ms = (time.perf_counter() - start_t) * 1000.0

        # Update Telemetry
        with self._lock:
            self._total_evaluations += 1
            if matched_entry:
                self._total_hits += 1
            self._latency_samples.append(elapsed_ms)
            self._last_evaluation_at = now_utc

        return WatchlistMatchResult(
            is_match=matched_entry is not None,
            match_type=match_type,
            matched_plate=matched_entry["registration_normalized"] if matched_entry else None,
            category=matched_entry["category"] if matched_entry else None,
            priority=matched_entry["priority"] if matched_entry else None,
            notes=matched_entry["notes"] if matched_entry else None,
            alert_generated=alert_generated,
            alert_id=alert_id,
            evaluation_time_ms=round(elapsed_ms, 2),
        )

    # ------------------ CRUD Operations ------------------

    async def create_watchlist(self, db: AsyncSession, data: WatchlistCreate) -> WatchlistResponse:
        """Create a new categorized Watchlist container."""
        w_id = uuid.uuid4().hex
        w = Watchlist(
            id=w_id,
            name=data.name,
            description=data.description,
            category=data.category,
            is_active=data.is_active,
        )
        db.add(w)
        await db.commit()
        await db.refresh(w)
        return WatchlistResponse(
            id=w.id,
            name=w.name,
            description=w.description,
            category=w.category,
            is_active=w.is_active,
            entry_count=0,
            created_at=w.created_at,
            updated_at=w.updated_at,
        )

    async def get_watchlists(self, db: AsyncSession) -> List[WatchlistResponse]:
        """List all watchlists with their current entry counts."""
        stmt = select(Watchlist).order_by(Watchlist.name)
        res = await db.execute(stmt)
        watchlists = res.scalars().all()

        responses: List[WatchlistResponse] = []
        for w in watchlists:
            responses.append(
                WatchlistResponse(
                    id=w.id,
                    name=w.name,
                    description=w.description,
                    category=w.category,
                    is_active=w.is_active,
                    entry_count=len(w.entries),
                    created_at=w.created_at,
                    updated_at=w.updated_at,
                )
            )
        return responses

    async def create_entry(
        self, db: AsyncSession, data: WatchlistEntryCreate
    ) -> WatchlistEntryResponse:
        """Add a new vehicle plate entry to a watchlist and update the in-memory cache."""
        norm = data.registration_normalized or data.registration_number.strip().upper().replace(
            " ", ""
        )
        entry_id = uuid.uuid4().hex
        entry = WatchlistEntry(
            id=entry_id,
            watchlist_id=data.watchlist_id,
            registration_number=data.registration_number,
            registration_normalized=norm,
            category=data.category,
            priority=data.priority,
            is_active=data.is_active,
            notes=data.notes,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

        # Synchronize in-memory cache
        await self.sync_cache(db)

        return WatchlistEntryResponse(
            id=entry.id,
            watchlist_id=entry.watchlist_id,
            registration_number=entry.registration_number,
            registration_normalized=entry.registration_normalized,
            category=entry.category,
            priority=entry.priority,
            is_active=entry.is_active,
            notes=entry.notes,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    async def bulk_import(
        self, db: AsyncSession, req: BulkWatchlistImportRequest
    ) -> BulkWatchlistImportResponse:
        """Bulk import police hotlist plate entries into a watchlist container."""
        # Find or create watchlist
        w_stmt = select(Watchlist).where(Watchlist.name == req.watchlist_name)
        w_res = await db.execute(w_stmt)
        w = w_res.scalar_one_or_none()

        if not w:
            w_id = uuid.uuid4().hex
            w = Watchlist(
                id=w_id,
                name=req.watchlist_name,
                category=req.category,
                description=f"Bulk imported hotlist on {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            )
            db.add(w)
            await db.commit()

        imported_count = 0
        skipped_count = 0
        errors: List[str] = []

        for item in req.items:
            try:
                norm = item.registration_number.strip().upper().replace(" ", "")
                if not norm:
                    skipped_count += 1
                    continue

                e = WatchlistEntry(
                    id=uuid.uuid4().hex,
                    watchlist_id=w.id,
                    registration_number=item.registration_number,
                    registration_normalized=norm,
                    category=item.category or req.category,
                    priority=item.priority,
                    notes=item.notes,
                )
                db.add(e)
                imported_count += 1
            except Exception as ex:
                errors.append(f"Failed to import {item.registration_number}: {ex}")
                skipped_count += 1

        await db.commit()
        await self.sync_cache(db)

        return BulkWatchlistImportResponse(
            watchlist_id=w.id,
            imported_count=imported_count,
            skipped_count=skipped_count,
            errors=errors,
        )

    async def get_alerts(
        self, db: AsyncSession, limit: int = 50, status_filter: Optional[str] = None
    ) -> List[AlertResponse]:
        """Fetch latest dispatched alerts with optional status filter."""
        stmt = select(Alert).order_by(desc(Alert.alert_time)).limit(limit)
        if status_filter:
            stmt = stmt.where(Alert.status == status_filter)

        res = await db.execute(stmt)
        alerts = res.scalars().all()

        return [
            AlertResponse(
                id=a.id,
                vehicle_event_id=a.vehicle_event_id,
                watchlist_entry_id=a.watchlist_entry_id,
                camera_id=a.camera_id,
                registration_number=a.registration_number,
                category=a.category,
                priority=a.priority,
                status=a.status,
                alert_time=a.alert_time,
                confidence=a.confidence,
                location_name=a.location_name,
                snapshot_path=a.snapshot_path,
                acknowledged_by=a.acknowledged_by,
                acknowledged_at=a.acknowledged_at,
                resolution_notes=a.resolution_notes,
                created_at=a.created_at,
            )
            for a in alerts
        ]

    async def acknowledge_alert(
        self, db: AsyncSession, alert_id: str, req: AlertAcknowledgeRequest
    ) -> Optional[AlertResponse]:
        """Record operator acknowledgment and audit trail on a dispatched alert."""
        stmt = select(Alert).where(Alert.id == alert_id)
        res = await db.execute(stmt)
        alert = res.scalar_one_or_none()
        if not alert:
            return None

        now = datetime.now(timezone.utc)
        alert.status = req.status
        alert.acknowledged_by = req.operator_name
        alert.acknowledged_at = now
        alert.resolution_notes = req.resolution_notes

        audit = AlertEvent(
            id=uuid.uuid4().hex,
            alert_id=alert.id,
            action=req.status,
            performed_by=req.operator_name,
            notes=req.resolution_notes,
        )
        db.add(audit)
        await db.commit()
        await db.refresh(alert)

        return AlertResponse(
            id=alert.id,
            vehicle_event_id=alert.vehicle_event_id,
            watchlist_entry_id=alert.watchlist_entry_id,
            camera_id=alert.camera_id,
            registration_number=alert.registration_number,
            category=alert.category,
            priority=alert.priority,
            status=alert.status,
            alert_time=alert.alert_time,
            confidence=alert.confidence,
            location_name=alert.location_name,
            snapshot_path=alert.snapshot_path,
            acknowledged_by=alert.acknowledged_by,
            acknowledged_at=alert.acknowledged_at,
            resolution_notes=alert.resolution_notes,
            created_at=alert.created_at,
        )

    async def get_entries(
        self, db: AsyncSession, watchlist_id: Optional[str] = None
    ) -> List[WatchlistEntryResponse]:
        stmt = select(WatchlistEntry).order_by(WatchlistEntry.created_at.desc())
        if watchlist_id:
            stmt = stmt.where(WatchlistEntry.watchlist_id == watchlist_id)
        result = await db.execute(stmt)
        entries = result.scalars().all()
        return [
            WatchlistEntryResponse(
                id=e.id,
                watchlist_id=e.watchlist_id,
                registration_number=e.registration_number,
                registration_normalized=e.registration_normalized,
                category=e.category,
                priority=e.priority,
                is_active=e.is_active,
                notes=e.notes,
                created_by=e.created_by,
                created_at=e.created_at,
                updated_at=e.updated_at,
            )
            for e in entries
        ]

    def get_telemetry(self) -> WatchlistTelemetry:
        """Retrieve real-time watchlist evaluation throughput and latency metrics."""
        with self._lock:
            samples = list(self._latency_samples)
            avg_lat = sum(samples) / len(samples) if samples else 0.0
            sub_50_count = sum(1 for s in samples if s <= 50.0)
            compliance = (sub_50_count / len(samples)) * 100.0 if samples else 100.0

            return WatchlistTelemetry(
                total_evaluations=self._total_evaluations,
                total_hits=self._total_hits,
                active_watchlist_entries_cached=len(self._exact_cache) + len(self._wildcard_cache),
                average_evaluation_time_ms=round(avg_lat, 2),
                sub_50ms_compliance_rate=round(compliance, 2),
                last_evaluation_at=self._last_evaluation_at,
            )


# Global singleton instance
watchlist_service = WatchlistMatchingEngine()
