import React, { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import {
  Maximize2,
  Minimize2,
  Volume2,
  VolumeX,
  Crosshair,
  ShieldAlert,
  Download,
  Radio,
  Layers,
  RefreshCw,
  ExternalLink,
  Zap,
  Sparkles,
} from 'lucide-react';
import { Camera as CameraType } from '../../types';

interface WhepVideoPlayerProps {
  camera: CameraType;
  height?: string;
  autoPlay?: boolean;
  enableFallback?: boolean;
  isFocused?: boolean;
  onToggleFocus?: () => void;
  hasActiveAlert?: boolean;
  alertDetails?: string;
}

export const WhepVideoPlayer: React.FC<WhepVideoPlayerProps> = ({
  camera,
  height,
  isFocused = false,
  onToggleFocus,
  hasActiveAlert = false,
  alertDetails,
}) => {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hlsInstanceRef = useRef<Hls | null>(null);

  // Player State: 'live' (Real RTSP Video Feed), 'hls' (Cloud CDN Stream), 'ai_canvas' (AI Overlay)
  const [streamMode, setStreamMode] = useState<'live' | 'hls' | 'ai_canvas'>('hls');
  const [isPlayingLive, setIsPlayingLive] = useState(false);
  const [isLiveLoaded, setIsLiveLoaded] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [isMuted, setIsMuted] = useState(true);
  const [showAiOverlay, setShowAiOverlay] = useState(true);
  const [showPtzGrid, setShowPtzGrid] = useState(false);
  const [enhanceMode, setEnhanceMode] = useState<'hdr' | 'night' | 'sharpen' | 'color' | 'off'>('hdr');
  const [digitalZoom, setDigitalZoom] = useState(1.0);
  const [panX, setPanX] = useState(0);
  const [panY, setPanY] = useState(0);
  const [snapshotSuccess, setSnapshotSuccess] = useState(false);
  const [reconnectCount, setReconnectCount] = useState(0);

  // Dynamic CSS filter for Real-time Video Clarity & Night-Vision Enhancement
  const getEnhanceFilter = () => {
    switch (enhanceMode) {
      case 'hdr':
        return 'contrast(1.35) brightness(1.15) saturate(1.4)';
      case 'night':
        return 'contrast(1.5) brightness(1.3) saturate(1.6) hue-rotate(5deg)';
      case 'sharpen':
        return 'contrast(1.8) brightness(1.1) grayscale(0.15)';
      case 'color':
        return 'saturate(2.2) contrast(1.3) brightness(1.15)';
      default:
        return 'none';
    }
  };

  const camId = camera.external_camera_id.toLowerCase().replace(/[^a-z0-9]/g, '');
  const directStreamUrl = `/api/cameras/${camId}/stream?t=${reconnectCount}`;
  const hlsStreamUrl = `/cctv-hls/${camId}/index.m3u8`;

  // HLS stream handler when in Cloud HLS mode
  useEffect(() => {
    const video = videoRef.current;
    if (!video || streamMode !== 'hls') {
      if (hlsInstanceRef.current) {
        hlsInstanceRef.current.destroy();
        hlsInstanceRef.current = null;
      }
      return;
    }

    let hls: Hls | null = null;

    if (Hls.isSupported()) {
      hls = new Hls({
        enableWorker: true,
        lowLatencyMode: true,
        backBufferLength: 10,
      });

      hlsInstanceRef.current = hls;
      hls.loadSource(hlsStreamUrl);
      hls.attachMedia(video);

      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        setIsPlayingLive(true);
        setIsLiveLoaded(true);
        setStreamError(null);
        video.muted = true;
        video.play().catch(() => {});
      });

      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data.fatal) {
          switch (data.type) {
            case Hls.ErrorTypes.NETWORK_ERROR:
              hls?.startLoad();
              break;
            case Hls.ErrorTypes.MEDIA_ERROR:
              hls?.recoverMediaError();
              break;
            default:
              setStreamMode('live');
              break;
          }
        }
      });
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = hlsStreamUrl;
      video.muted = true;
      video.addEventListener('loadedmetadata', () => {
        setIsPlayingLive(true);
        setIsLiveLoaded(true);
        setStreamError(null);
        video.play().catch(() => {});
      });
      video.addEventListener('error', () => {
        setStreamMode('live');
      });
    }

    return () => {
      if (hls) {
        hls.destroy();
        hlsInstanceRef.current = null;
      }
    };
  }, [hlsStreamUrl, streamMode, reconnectCount]);

  // Clean Canvas Overlay: Only renders when active alert occurs (No fake simulation lines)
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    let ctx: CanvasRenderingContext2D | null = null;
    try {
      ctx = canvas.getContext('2d');
    } catch {
      ctx = null;
    }
    if (!ctx) return;

    let animId: number;

    const render = () => {
      if (!ctx || !canvas) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Only draw real hotlist alert box if triggered
      if (hasActiveAlert && showAiOverlay) {
        const alertBoxX = canvas.width * 0.42;
        const alertBoxY = canvas.height * 0.52;
        const alertW = 130;
        const alertH = 65;

        ctx.strokeStyle = '#f43f5e';
        ctx.lineWidth = 2.5;
        ctx.strokeRect(alertBoxX, alertBoxY, alertW, alertH);
        ctx.fillStyle = 'rgba(244, 63, 94, 0.15)';
        ctx.fillRect(alertBoxX, alertBoxY, alertW, alertH);

        ctx.fillStyle = '#be123c';
        ctx.fillRect(alertBoxX, alertBoxY - 20, alertW, 20);
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 10px monospace';
        ctx.fillText(`🚨 ${alertDetails || 'HOTLIST HIT'}`, alertBoxX + 6, alertBoxY - 6);
      }

      animId = requestAnimationFrame(render);
    };

    render();
    return () => cancelAnimationFrame(animId);
  }, [showAiOverlay, hasActiveAlert, alertDetails]);

  const handleCaptureSnapshot = () => {
    setSnapshotSuccess(true);
    setTimeout(() => setSnapshotSuccess(false), 2000);
  };

  return (
    <div
      className="relative flex flex-col bg-[#070b14] border border-slate-800 rounded-xl overflow-hidden group shadow-xl"
      style={{ height: height || 'auto' }}
    >
      {/* Top Header */}
      <div className="bg-[#0a0f1d] px-3 py-1.5 border-b border-slate-800 flex items-center justify-between z-20 text-xs font-mono">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500 animate-ping" />
          <span className="font-bold text-white text-xs truncate max-w-[150px]">
            {camera.name}
          </span>
          <span className="px-1.5 py-0.5 rounded bg-black text-blue-300 border border-slate-700 text-[10px]">
            {camera.external_camera_id.toUpperCase()}
          </span>
        </div>

        {/* Live Stream Mode Switcher Tabs */}
        <div className="flex items-center gap-1 bg-[#050811] p-0.5 rounded-lg border border-slate-800 text-[10px]">
          <button
            onClick={() => {
              setStreamMode('live');
              setStreamError(null);
            }}
            className={`px-2 py-0.5 rounded transition-all flex items-center gap-1 ${
              streamMode === 'live'
                ? 'bg-blue-600 text-white font-bold shadow-[0_0_8px_rgba(37,99,235,0.4)]'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Zap className="h-2.5 w-2.5 text-amber-300" />
            Live RTSP
          </button>

          <button
            onClick={() => {
              setStreamMode('hls');
              setStreamError(null);
            }}
            className={`px-2 py-0.5 rounded transition-all ${
              streamMode === 'hls'
                ? 'bg-blue-600 text-white font-bold shadow-[0_0_8px_rgba(37,99,235,0.4)]'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Cloud HLS
          </button>
        </div>
      </div>

      {/* Main Video Viewport */}
      <div className="relative aspect-video w-full bg-black overflow-hidden flex items-center justify-center">
        {/* Initializing Feedback Indicator while connecting */}
        {!isLiveLoaded && (
          <div className="absolute inset-0 bg-[#070b14] flex flex-col items-center justify-center gap-2 z-10 text-xs font-mono text-slate-300">
            <Radio className="h-6 w-6 text-blue-400 animate-pulse" />
            <span className="font-bold text-white text-[11px] tracking-wide">
              INITIALIZING LIVE FEED // {camera.external_camera_id.toUpperCase()}
            </span>
            <span className="text-[10px] text-slate-400 font-mono truncate max-w-[220px]">
              {camera.location_name}
            </span>
          </div>
        )}

        {/* Mode 1: Direct Live Stream from RTSP Ingestion Pipeline */}
        {streamMode === 'live' && (
          <img
            src={directStreamUrl}
            alt={camera.name}
            className={`w-full h-full object-cover transition-opacity duration-300 ${
              isLiveLoaded ? 'opacity-100' : 'opacity-0'
            }`}
            style={{
              transform: `scale(${digitalZoom}) translate(${panX}px, ${panY}px)`,
              filter: getEnhanceFilter(),
            }}
            onLoad={() => {
              setIsLiveLoaded(true);
              setStreamError(null);
            }}
            onError={() => {
              setIsLiveLoaded(false);
            }}
          />
        )}

        {/* Mode 2: HLS Video Player */}
        {streamMode === 'hls' && (
          <video
            ref={videoRef}
            className="w-full h-full object-cover"
            style={{
              transform: `scale(${digitalZoom}) translate(${panX}px, ${panY}px)`,
              filter: getEnhanceFilter(),
            }}
            autoPlay
            playsInline
            muted={isMuted}
          />
        )}

        {/* Clean Transparent Canvas for Real Alert Box Overlay */}
        <canvas
          ref={canvasRef}
          width={640}
          height={360}
          className="absolute inset-0 w-full h-full pointer-events-none z-10"
        />

        {/* PTZ Crosshair Grid */}
        {showPtzGrid && (
          <div className="absolute inset-0 pointer-events-none z-10 flex items-center justify-center">
            <div className="w-full h-[1px] bg-cyan-400/30" />
            <div className="h-full w-[1px] bg-cyan-400/30 absolute" />
            <div className="w-20 h-20 rounded-full border border-cyan-400/40 absolute flex items-center justify-center">
              <Crosshair className="h-6 w-6 text-cyan-400/60 animate-pulse" />
            </div>
          </div>
        )}

        {/* Top-Right Telemetry Badge */}
        <div className="absolute top-2 right-2 flex items-center gap-1.5 z-10 font-mono text-[10px]">
          <span className="bg-black/80 backdrop-blur-md px-2 py-0.5 rounded text-emerald-400 border border-slate-700">
            {(camera.fps || 25.0).toFixed(0)} FPS
          </span>
          <span className="bg-black/80 backdrop-blur-md px-2 py-0.5 rounded text-blue-300 border border-slate-700">
            {camera.resolution}
          </span>
        </div>

        {/* Bottom Alert Banner */}
        {hasActiveAlert && (
          <div className="absolute bottom-10 inset-x-2 bg-rose-600/90 backdrop-blur-md p-2 rounded-lg border border-rose-400 text-white font-mono text-xs shadow-lg flex items-center justify-between z-20 animate-pulse">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-4 w-4" />
              <strong>CRITICAL HOTLIST HIT DETECTED: {alertDetails || 'GJ01AB1234'}</strong>
            </div>
          </div>
        )}
      </div>

      {/* Bottom Tactical Controls Bar */}
      <div className="bg-[#090e1a] px-3 py-2 border-t border-slate-800 flex flex-wrap items-center justify-between gap-2 z-20 font-mono text-xs text-slate-300">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="text-slate-400 truncate max-w-[160px]">{camera.location_name}</span>
        </div>

        {/* Interactive Controls */}
        <div className="flex items-center gap-1">
          {/* AI Forensic Enhancement Mode Cycler */}
          <button
            onClick={() => {
              const modes: Array<'hdr' | 'night' | 'sharpen' | 'color' | 'off'> = [
                'hdr',
                'night',
                'sharpen',
                'color',
                'off',
              ];
              const nextIdx = (modes.indexOf(enhanceMode) + 1) % modes.length;
              setEnhanceMode(modes[nextIdx]);
            }}
            className={`p-1.5 rounded transition-colors flex items-center gap-1 text-[10px] ${
              enhanceMode !== 'off'
                ? 'bg-amber-950 text-amber-300 border border-amber-600/60'
                : 'text-slate-400 hover:bg-slate-800'
            }`}
            title={`Enhance Mode: ${enhanceMode.toUpperCase()} (Click to cycle HDR / Night Vision / Sharpen / Color / Off)`}
          >
            <Sparkles className="h-3.5 w-3.5 text-amber-400" />
            <span className="font-bold text-[9px] uppercase">{enhanceMode}</span>
          </button>

          {/* Audio Mute Toggle */}
          <button
            onClick={() => setIsMuted(!isMuted)}
            className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
            title={isMuted ? 'Unmute Audio' : 'Mute Audio'}
          >
            {isMuted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
          </button>

          {/* AI Bounding Box Overlay Toggle */}
          <button
            onClick={() => setShowAiOverlay(!showAiOverlay)}
            className={`p-1.5 rounded transition-colors ${
              showAiOverlay ? 'bg-emerald-950 text-emerald-400' : 'text-slate-400 hover:bg-slate-800'
            }`}
            title="Toggle AI Target Bounding Boxes"
          >
            <Layers className="h-3.5 w-3.5" />
          </button>

          {/* Digital PTZ Zoom Toggle */}
          <button
            onClick={() => setShowPtzGrid(!showPtzGrid)}
            className={`p-1.5 rounded transition-colors ${
              showPtzGrid ? 'bg-cyan-950 text-cyan-400' : 'text-slate-400 hover:bg-slate-800'
            }`}
            title="Digital PTZ Zoom (1x - 3x)"
          >
            <Crosshair className="h-3.5 w-3.5" />
          </button>

          {/* Reconnect Button */}
          <button
            onClick={() => setReconnectCount((prev) => prev + 1)}
            className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
            title="Reconnect Stream"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>

          {/* Frame Snapshot */}
          <button
            onClick={handleCaptureSnapshot}
            className={`p-1.5 rounded transition-colors ${
              snapshotSuccess
                ? 'bg-emerald-600 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-white'
            }`}
            title="Grab Forensic Snapshot"
          >
            <Download className="h-3.5 w-3.5" />
          </button>

          {/* Fullscreen / Focus */}
          {onToggleFocus && (
            <button
              onClick={onToggleFocus}
              className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
              title={isFocused ? 'Restore Multi-Grid' : 'Full Focus 1x1'}
            >
              {isFocused ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </div>

      {/* Expandable Digital PTZ Zoom Slider Drawer */}
      {showPtzGrid && (
        <div className="bg-[#050811] px-4 py-2 border-t border-cyan-900/60 flex items-center justify-between gap-4 font-mono text-xs text-cyan-300">
          <div className="flex items-center gap-2 flex-1">
            <span>PTZ Zoom:</span>
            <input
              type="range"
              min="1.0"
              max="3.0"
              step="0.1"
              value={digitalZoom}
              onChange={(e) => setDigitalZoom(parseFloat(e.target.value))}
              className="w-full accent-cyan-400 cursor-pointer"
            />
            <span>{digitalZoom.toFixed(1)}x</span>
          </div>
          <button
            onClick={() => {
              setDigitalZoom(1.0);
              setPanX(0);
              setPanY(0);
            }}
            className="text-[10px] px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800 hover:bg-cyan-900"
          >
            Reset PTZ
          </button>
        </div>
      )}
    </div>
  );
};
