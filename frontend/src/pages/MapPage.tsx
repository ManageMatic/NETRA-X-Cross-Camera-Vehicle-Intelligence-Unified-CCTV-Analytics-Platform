import React, { useState, useEffect, useMemo } from 'react';
import {
  Activity,
  Calendar,
  CheckCircle2,
  Clock,
  Compass,
  Eye,
  FastForward,
  Layers,
  MapPin,
  Maximize2,
  Navigation,
  Pause,
  Play,
  Radio,
  RotateCcw,
  Search,
  ShieldAlert,
  Sliders,
  TrendingUp,
  Zap,
} from 'lucide-react';
import { Camera, VehicleJourney, JourneyWaypoint } from '../types';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { TacticalLeafletMap } from '../components/gis/TacticalLeafletMap';
import { fetchJourney } from '../services/api';


const buildJourneyFromCameras = (cams: Camera[], plate: string = 'GJ01AB1234'): VehicleJourney => {
  const waypoints: JourneyWaypoint[] = (cams.length > 0 ? cams.slice(0, 4) : []).map((cam, idx) => ({
    order: idx + 1,
    camera_id: cam.id,
    camera_name: cam.name,
    location: cam.location_name,
    latitude: cam.latitude,
    longitude: cam.longitude,
    timestamp: new Date(Date.now() - (4 - idx) * 15 * 60000).toISOString(),
    speed_kmh: 45 + idx * 5,
    travel_duration_minutes: idx * 15,
    distance_km: idx * 6.5,
    snapshot_url: 'https://images.unsplash.com/photo-1549399542-7e3f8b79c341?w=400',
    is_plausible: true,
  }));

  return {
    registration: plate,
    vehicle_class: 'car',
    total_sightings: waypoints.length,
    first_seen: waypoints[0]?.timestamp || new Date().toISOString(),
    last_seen: waypoints[waypoints.length - 1]?.timestamp || new Date().toISOString(),
    total_distance_km: waypoints.length * 6.5,
    waypoints,
  };
};

interface MapPageProps {
  cameras: Camera[];
  journey?: VehicleJourney | null;
}

export const MapPage: React.FC<MapPageProps> = ({ cameras = [], journey: initialJourney }) => {
  // Master Cameras
  const masterCameras = cameras;

  // State Management
  const [selectedJourneyKey, setSelectedJourneyKey] = useState<string>('GJ01AB1234');
  const [activeJourney, setActiveJourney] = useState<VehicleJourney | null>(initialJourney || buildJourneyFromCameras(cameras, 'GJ01AB1234'));
  const [activeWaypointIndex, setActiveWaypointIndex] = useState<number | null>(0);
  const [selectedCameraId, setSelectedCameraId] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState<number>(1);
  const [sidebarTab, setSidebarTab] = useState<'sightings' | 'cameras'>('sightings');
  const [cameraSearchQuery, setCameraSearchQuery] = useState('');
  const [selectedDistrict, setSelectedDistrict] = useState<string>('ALL');

  // Layer Toggles
  const [showCamerasLayer, setShowCamerasLayer] = useState(true);
  const [showTrajectoryLayer, setShowTrajectoryLayer] = useState(true);
  const [showSpeedLayer, setShowSpeedLayer] = useState(true);
  const [showLoiteringLayer, setShowLoiteringLayer] = useState(true);

  // Map Coordinates & Zoom Preset
  const [mapCenter, setMapCenter] = useState<[number, number]>([23.0225, 72.5714]);
  const [mapZoom, setMapZoom] = useState<number>(11);

  // Synchronize Journey on Prop Change or Mount
  useEffect(() => {
    if (initialJourney) {
      setActiveJourney(initialJourney);
      setActiveWaypointIndex(0);
      if (initialJourney.waypoints && initialJourney.waypoints.length > 0) {
        setMapCenter([initialJourney.waypoints[0].latitude, initialJourney.waypoints[0].longitude]);
        setMapZoom(12);
      }
    } else {
      fetchJourney('GJ01AB1234').then((j) => {
        if (j && j.waypoints && j.waypoints.length > 0) {
          setActiveJourney(j);
          setActiveWaypointIndex(0);
          setMapCenter([j.waypoints[0].latitude, j.waypoints[0].longitude]);
          setMapZoom(12);
        }
      });
    }
  }, [initialJourney]);

  // Synchronize Journey when Plate Preset Selected
  const handleSelectJourneyPreset = (key: string) => {
    setSelectedJourneyKey(key);
    if (key === 'NONE') {
      setActiveJourney(null);
      setActiveWaypointIndex(null);
    } else {
      const fallback = buildJourneyFromCameras(masterCameras, key);
      setActiveJourney(fallback);
      setActiveWaypointIndex(0);
      if (fallback.waypoints.length > 0) {
        setMapCenter([fallback.waypoints[0].latitude, fallback.waypoints[0].longitude]);
        setMapZoom(12);
      }

      fetchJourney(key)
        .then((liveJourney) => {
          if (liveJourney && liveJourney.waypoints && liveJourney.waypoints.length > 0) {
            setActiveJourney(liveJourney);
            setActiveWaypointIndex(0);
            setMapCenter([liveJourney.waypoints[0].latitude, liveJourney.waypoints[0].longitude]);
          }
        })
        .catch((err) => {
          console.error('Failed to load live journey for plate:', key, err);
        });
    }
  };

  // Playback Animation Timer
  useEffect(() => {
    let timer: NodeJS.Timeout | null = null;
    if (isPlaying && activeJourney && activeJourney.waypoints.length > 0) {
      const intervalMs = 2000 / playbackSpeed;
      timer = setInterval(() => {
        setActiveWaypointIndex((prev) => {
          const nextIndex = (prev === null ? 0 : prev + 1) % activeJourney.waypoints.length;
          const currentWaypoint = activeJourney.waypoints[nextIndex];
          if (currentWaypoint) {
            setMapCenter([currentWaypoint.latitude, currentWaypoint.longitude]);
          }
          return nextIndex;
        });
      }, intervalMs);
    }
    return () => {
      if (timer) clearInterval(timer);
    };
  }, [isPlaying, activeJourney, playbackSpeed]);

  // District Quick Jump Handlers
  const handleDistrictJump = (district: string) => {
    setSelectedDistrict(district);
    switch (district) {
      case 'AHMEDABAD':
        setMapCenter([23.0225, 72.5714]);
        setMapZoom(12);
        break;
      case 'SURAT':
        setMapCenter([21.1959, 72.8302]);
        setMapZoom(12);
        break;
      case 'VADODARA':
        setMapCenter([22.3107, 73.1812]);
        setMapZoom(12);
        break;
      case 'GANDHINAGAR':
        setMapCenter([23.2156, 72.6369]);
        setMapZoom(13);
        break;
      case 'RAJKOT':
        setMapCenter([22.3039, 70.8022]);
        setMapZoom(12);
        break;
      default: // STATEWIDE ALL
        setMapCenter([22.2587, 71.1924]);
        setMapZoom(7);
        break;
    }
  };

  // Filtered Cameras
  const filteredCameras = useMemo(() => {
    return masterCameras.filter((cam) => {
      const matchesSearch =
        cam.name.toLowerCase().includes(cameraSearchQuery.toLowerCase()) ||
        cam.location_name.toLowerCase().includes(cameraSearchQuery.toLowerCase()) ||
        cam.external_camera_id.toLowerCase().includes(cameraSearchQuery.toLowerCase());
      const matchesDistrict =
        selectedDistrict === 'ALL' ||
        cam.location_name.toLowerCase().includes(selectedDistrict.toLowerCase());
      return matchesSearch && matchesDistrict;
    });
  }, [masterCameras, cameraSearchQuery, selectedDistrict]);

  // Active Selected Waypoint
  const currentWaypoint =
    activeJourney && activeWaypointIndex !== null
      ? activeJourney.waypoints[activeWaypointIndex]
      : null;

  return (
    <div className="space-y-6">
      {/* Top Tactical Command Header */}
      <div className="bg-[#0c1424] p-4 rounded-xl border border-slate-800 shadow-2xl flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <Compass className="h-5 w-5 text-blue-400 animate-spin-slow" />
            <h1 className="text-xl font-black text-white font-mono tracking-wide">
              GIS OPENSTREETMAP TACTICAL RADAR
            </h1>
          </div>
          <p className="text-xs text-slate-400 mt-0.5 font-mono">
            Statewide Gujarat Police Geospatial Radar & Chronological Trajectory Intelligence
          </p>
        </div>

        {/* Action Presets & Trajectory Selector */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Preset Selector */}
          <div className="flex items-center gap-2 bg-[#070b14] p-1.5 rounded-lg border border-slate-800 text-xs font-mono">
            <span className="text-slate-400 pl-1">TRACK:</span>
            <select
              value={selectedJourneyKey}
              onChange={(e) => handleSelectJourneyPreset(e.target.value)}
              className="bg-transparent text-yellow-400 font-bold focus:outline-none cursor-pointer"
            >
              <option value="GJ01AB1234" className="bg-[#070b14] text-white">
                GJ01AB1234 (Live Reconstructed Trajectory)
              </option>
              <option value="GJ05CD5678" className="bg-[#070b14] text-white">
                GJ05CD5678 (Vadodara-Surat Live Trajectory)
              </option>
              <option value="NONE" className="bg-[#070b14] text-white">
                [No Active Trajectory — CCTV Only]
              </option>
            </select>
          </div>

          {/* Layer Controls Dropdown */}
          <div className="flex items-center bg-[#070b14] p-1 rounded-lg border border-slate-800 text-xs font-mono">
            <button
              onClick={() => setShowCamerasLayer(!showCamerasLayer)}
              className={`px-2.5 py-1 rounded transition-colors ${
                showCamerasLayer ? 'bg-blue-600 text-white font-bold' : 'text-slate-400 hover:text-white'
              }`}
              title="Toggle CCTV Camera Markers"
            >
              Cameras
            </button>
            <button
              onClick={() => setShowTrajectoryLayer(!showTrajectoryLayer)}
              className={`px-2.5 py-1 rounded transition-colors ${
                showTrajectoryLayer
                  ? 'bg-blue-600 text-white font-bold'
                  : 'text-slate-400 hover:text-white'
              }`}
              title="Toggle Trajectory Polylines"
            >
              Polylines
            </button>
            <button
              onClick={() => setShowSpeedLayer(!showSpeedLayer)}
              className={`px-2.5 py-1 rounded transition-colors ${
                showSpeedLayer ? 'bg-blue-600 text-white font-bold' : 'text-slate-400 hover:text-white'
              }`}
              title="Toggle Speed & Feasibility Badges"
            >
              Speed
            </button>
            <button
              onClick={() => setShowLoiteringLayer(!showLoiteringLayer)}
              className={`px-2.5 py-1 rounded transition-colors ${
                showLoiteringLayer
                  ? 'bg-amber-600 text-white font-bold'
                  : 'text-slate-400 hover:text-white'
              }`}
              title="Toggle Loitering Proximity Zones"
            >
              Loitering
            </button>
          </div>
        </div>
      </div>

      {/* Gujarat District Hub Quick Jumps */}
      <div className="bg-[#090e1a] p-2.5 rounded-xl border border-slate-800 flex flex-wrap items-center justify-between gap-2 text-xs font-mono">
        <div className="flex items-center gap-2 text-slate-400">
          <MapPin className="h-4 w-4 text-blue-400" />
          <span className="font-bold text-slate-200">GUJARAT DISTRICT RADAR HUBS:</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {['ALL', 'AHMEDABAD', 'GANDHINAGAR', 'VADODARA', 'SURAT', 'RAJKOT'].map((dist) => (
            <button
              key={dist}
              onClick={() => handleDistrictJump(dist)}
              className={`px-3 py-1 rounded-md text-[11px] font-bold transition-all ${
                selectedDistrict === dist
                  ? 'bg-blue-600 text-white shadow-md shadow-blue-500/30'
                  : 'bg-[#070b14] text-slate-400 hover:text-white border border-slate-800'
              }`}
            >
              {dist === 'ALL' ? 'STATEWIDE OVERVIEW' : dist}
            </button>
          ))}
        </div>
      </div>

      {/* Main Tactical Map Screen & Timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left 3 Columns: Leaflet Dark GIS Canvas & Playback Bar */}
        <div className="lg:col-span-3 space-y-4">
          {/* Map Viewport */}
          <div className="h-[560px] relative shadow-2xl rounded-2xl overflow-hidden border border-slate-800">
            <TacticalLeafletMap
              cameras={filteredCameras}
              journey={activeJourney}
              activeWaypointIndex={activeWaypointIndex}
              selectedCameraId={selectedCameraId}
              onSelectCamera={(cam) => setSelectedCameraId(cam.id)}
              onSelectWaypoint={(wp, idx) => {
                setActiveWaypointIndex(idx);
                setMapCenter([wp.latitude, wp.longitude]);
              }}
              showCamerasLayer={showCamerasLayer}
              showTrajectoryLayer={showTrajectoryLayer}
              showSpeedLayer={showSpeedLayer}
              showLoiteringLayer={showLoiteringLayer}
              centerCoordinates={mapCenter}
              zoomLevel={mapZoom}
            />
          </div>

          {/* Interactive Trajectory Timeline & Playback Controller */}
          {activeJourney && (
            <div className="bg-[#0c1424] p-4 rounded-xl border border-slate-800 shadow-xl space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-4">
                {/* Vehicle Identification & Metrics */}
                <div className="flex items-center gap-3 font-mono">
                  <div className="px-3 py-1 bg-black border-2 border-yellow-400 rounded-lg text-yellow-300 font-black text-sm tracking-wider shadow-inner">
                    {activeJourney.registration}
                  </div>
                  <span className="text-xs text-slate-400 uppercase">
                    Class: <strong className="text-white">{activeJourney.vehicle_class}</strong>
                  </span>
                  <span className="text-xs text-slate-400">
                    Sightings: <strong className="text-amber-400">{activeJourney.waypoints.length} Cams</strong>
                  </span>
                  <span className="text-xs text-slate-400">
                    Total: <strong className="text-emerald-400">{activeJourney.total_distance_km} KM</strong>
                  </span>
                </div>

                {/* Playback Controls */}
                <div className="flex items-center gap-2">
                  <Button
                    variant={isPlaying ? 'danger' : 'primary'}
                    size="sm"
                    onClick={() => setIsPlaying(!isPlaying)}
                    icon={isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                  >
                    {isPlaying ? 'PAUSE' : 'PLAY REPLAY'}
                  </Button>

                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setIsPlaying(false);
                      setActiveWaypointIndex(0);
                      if (activeJourney.waypoints[0]) {
                        setMapCenter([
                          activeJourney.waypoints[0].latitude,
                          activeJourney.waypoints[0].longitude,
                        ]);
                      }
                    }}
                    icon={<RotateCcw className="h-3.5 w-3.5" />}
                  >
                    Reset
                  </Button>

                  {/* Playback Speed Switcher */}
                  <div className="flex items-center bg-[#070b14] p-1 rounded-lg border border-slate-800 text-xs font-mono">
                    {[1, 2, 5].map((spd) => (
                      <button
                        key={spd}
                        onClick={() => setPlaybackSpeed(spd)}
                        className={`px-2 py-0.5 rounded transition-colors ${
                          playbackSpeed === spd
                            ? 'bg-blue-600 text-white font-bold'
                            : 'text-slate-400 hover:text-white'
                        }`}
                      >
                        {spd}x
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Waypoint Chronological Stepper Track */}
              <div className="pt-2">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  {activeJourney.waypoints.map((wp, idx) => {
                    const isActive = activeWaypointIndex === idx;
                    return (
                      <button
                        key={wp.camera_id}
                        onClick={() => {
                          setIsPlaying(false);
                          setActiveWaypointIndex(idx);
                          setMapCenter([wp.latitude, wp.longitude]);
                        }}
                        className={`p-2.5 rounded-lg border text-left transition-all font-mono ${
                          isActive
                            ? 'bg-blue-950/60 border-amber-400 ring-2 ring-amber-400/30'
                            : 'bg-[#070b14] border-slate-800 hover:border-slate-700'
                        }`}
                      >
                        <div className="flex items-center justify-between text-xs">
                          <span
                            className={`font-bold ${
                              isActive ? 'text-amber-400' : 'text-slate-300'
                            }`}
                          >
                            Leg #{wp.order || idx + 1}
                          </span>
                          <span className="text-[10px] text-slate-500">
                            {new Date(wp.timestamp).toLocaleTimeString([], {
                              hour: '2-digit',
                              minute: '2-digit',
                            })}
                          </span>
                        </div>
                        <p className="text-[11px] text-white font-semibold truncate mt-1">
                          {wp.camera_name}
                        </p>
                        <div className="flex items-center justify-between text-[10px] text-slate-400 mt-1">
                          <span className="text-emerald-400">{wp.speed_kmh} km/h</span>
                          <span>+{wp.distance_km} km</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right 1 Column: Sighting Detail HUD & Active Camera Directory */}
        <div className="space-y-4">
          {/* Sidebar Tab Switcher */}
          <div className="bg-[#0c1424] p-1.5 rounded-xl border border-slate-800 flex items-center gap-1 text-xs font-mono">
            <button
              onClick={() => setSidebarTab('sightings')}
              className={`flex-1 py-1.5 rounded-lg text-center font-bold transition-all ${
                sidebarTab === 'sightings'
                  ? 'bg-blue-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              Sightings ({activeJourney?.waypoints.length || 0})
            </button>
            <button
              onClick={() => setSidebarTab('cameras')}
              className={`flex-1 py-1.5 rounded-lg text-center font-bold transition-all ${
                sidebarTab === 'cameras'
                  ? 'bg-blue-600 text-white shadow-md'
                  : 'text-slate-400 hover:text-white'
              }`}
            >
              GIS Nodes ({filteredCameras.length})
            </button>
          </div>

          {/* Tab 1: Chronological Sightings Drawer */}
          {sidebarTab === 'sightings' && activeJourney && (
            <Card
              title={`Chronological Journey`}
              subtitle={`Vehicle Plate: ${activeJourney.registration}`}
            >
              <div className="space-y-3 max-h-[580px] overflow-y-auto pr-1">
                {activeJourney.waypoints.map((wp, idx) => {
                  const isActive = activeWaypointIndex === idx;
                  return (
                    <div
                      key={wp.camera_id}
                      onClick={() => {
                        setIsPlaying(false);
                        setActiveWaypointIndex(idx);
                        setMapCenter([wp.latitude, wp.longitude]);
                      }}
                      className={`p-3 rounded-xl border cursor-pointer transition-all font-mono ${
                        isActive
                          ? 'bg-[#0e172a] border-amber-400 shadow-lg shadow-amber-500/10'
                          : 'bg-[#080d19] border-slate-800 hover:border-slate-700'
                      }`}
                    >
                      {/* Waypoint Header */}
                      <div className="flex items-center justify-between text-xs pb-1.5 border-b border-slate-800">
                        <span className="flex items-center gap-1.5 font-bold text-white">
                          <span className="w-5 h-5 rounded-full bg-blue-600 text-white flex items-center justify-center text-[10px]">
                            {wp.order || idx + 1}
                          </span>
                          {wp.camera_name}
                        </span>
                        <span className="text-[10px] text-slate-400">
                          {new Date(wp.timestamp).toLocaleTimeString()}
                        </span>
                      </div>

                      {/* Waypoint Location & Speed */}
                      <p className="text-[11px] text-slate-300 mt-2">{wp.location}</p>

                      <div className="grid grid-cols-2 gap-2 mt-2 pt-2 border-t border-slate-800/80 text-[10px]">
                        <div className="bg-[#060a12] p-1.5 rounded border border-slate-800">
                          <span className="text-slate-500 block">Velocity</span>
                          <span className="text-emerald-400 font-bold">{wp.speed_kmh} km/h</span>
                        </div>
                        <div className="bg-[#060a12] p-1.5 rounded border border-slate-800">
                          <span className="text-slate-500 block">Leg Distance</span>
                          <span className="text-blue-400 font-bold">{wp.distance_km} KM</span>
                        </div>
                      </div>

                      {/* Physical Plausibility Status */}
                      <div className="flex items-center justify-between text-[10px] mt-2 pt-1">
                        <span className="text-slate-400">Spatial-Temporal:</span>
                        <span
                          className={`font-bold flex items-center gap-1 ${
                            wp.is_plausible ? 'text-emerald-400' : 'text-rose-400'
                          }`}
                        >
                          {wp.is_plausible ? (
                            <>
                              <CheckCircle2 className="h-3 w-3" /> PLAUSIBLE
                            </>
                          ) : (
                            <>
                              <ShieldAlert className="h-3 w-3" /> SPEED ANOMALY
                            </>
                          )}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}

          {/* Tab 2: GIS Nodes / CCTV Cameras Search Directory */}
          {sidebarTab === 'cameras' && (
            <Card title="Active GIS Nodes" subtitle="All geocoded statewide cameras">
              <div className="space-y-3">
                {/* Search */}
                <div className="relative">
                  <Search className="h-3.5 w-3.5 absolute left-3 top-2.5 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Search node or junction..."
                    value={cameraSearchQuery}
                    onChange={(e) => setCameraSearchQuery(e.target.value)}
                    className="w-full bg-[#070b14] border border-slate-800 rounded-lg pl-8 pr-3 py-1.5 text-xs text-slate-200 font-mono focus:border-blue-500 focus:outline-none"
                  />
                </div>

                {/* Node List */}
                <div className="space-y-2 max-h-[500px] overflow-y-auto pr-1">
                  {filteredCameras.map((cam) => {
                    const isSelected = selectedCameraId === cam.id;
                    return (
                      <div
                        key={cam.id}
                        onClick={() => {
                          setSelectedCameraId(cam.id);
                          setMapCenter([cam.latitude, cam.longitude]);
                          setMapZoom(14);
                        }}
                        className={`p-3 rounded-lg border cursor-pointer transition-all text-xs font-mono ${
                          isSelected
                            ? 'bg-[#0f1a30] border-blue-500 shadow-md'
                            : 'bg-[#080d19] border-slate-800 hover:border-slate-700'
                        }`}
                      >
                        <div className="flex items-center justify-between text-white font-bold">
                          <span className="truncate">{cam.name}</span>
                          <span className="text-[10px] text-emerald-400 px-1.5 py-0.5 rounded bg-emerald-950">
                            {cam.live_status}
                          </span>
                        </div>
                        <p className="text-[10px] text-slate-400 mt-1">{cam.location_name}</p>
                        <div className="flex items-center justify-between text-[9px] text-slate-500 mt-1">
                          <span>ID: {cam.external_camera_id}</span>
                          <span>
                            {cam.latitude.toFixed(3)}, {cam.longitude.toFixed(3)}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
};
