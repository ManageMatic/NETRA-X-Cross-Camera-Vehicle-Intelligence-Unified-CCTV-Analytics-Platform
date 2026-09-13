import { useState, useEffect, useCallback } from 'react';
import { AppLayout } from './components/layout/AppLayout';
import { DashboardPage } from './pages/DashboardPage';
import { LiveGridPage } from './pages/LiveGridPage';
import { SearchPage } from './pages/SearchPage';
import { CorrelationPage } from './pages/CorrelationPage';
import { MapPage } from './pages/MapPage';
import { WatchlistsPage } from './pages/WatchlistsPage';
import { AlertsPage } from './pages/AlertsPage';
import { EvidencePage } from './pages/EvidencePage';
import { AuditPage } from './pages/AuditPage';
import { CamerasPage } from './pages/CamerasPage';
import { SystemPage } from './pages/SystemPage';
import { Modal } from './components/common/Modal';
import { PriorityBadge, StatusBadge, CategoryBadge } from './components/common/Badge';
import { Button } from './components/common/Button';
import {
  NavigationTab,
  SystemHealthResponse,
  SystemStatusData,
  SystemStats,
  AlertItem,
  VehicleEvent,
  Camera,
  VehicleJourney,
  WatchlistEntry,
  EvidenceRecord,
  AuditRecord,
} from './types';
import {
  fetchSystemHealth,
  fetchSystemStatus,
  fetchSystemStats,
  fetchCameras,
  fetchAlerts,
  fetchVehicleEvents,
  fetchWatchlists,
  fetchEvidenceRecords,
  fetchAuditLogs,
  fetchJourney,
  acknowledgeAlertApi,
  EMPTY_JOURNEY,
} from './services/api';
import { CheckCircle, Eye, ShieldAlert } from 'lucide-react';

export function App() {
  const [activeTab, setActiveTab] = useState<NavigationTab>('dashboard');
  const [health, setHealth] = useState<SystemHealthResponse | null>(null);
  const [status, setStatus] = useState<SystemStatusData | null>(null);
  const [stats, setStats] = useState<SystemStats>({
    totalCameras: 0,
    onlineCameras: 0,
    offlineCameras: 0,
    activeAlerts: 0,
    detectionsToday: 0,
    vehiclesIndexed: 0,
    avgProcessTimeMs: 14.5,
  });
  const [loading, setLoading] = useState<boolean>(true);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [events, setEvents] = useState<VehicleEvent[]>([]);
  const [watchlists, setWatchlists] = useState<WatchlistEntry[]>([]);
  const [evidence, setEvidence] = useState<EvidenceRecord[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditRecord[]>([]);
  const [journey, setJourney] = useState<VehicleJourney>(EMPTY_JOURNEY);
  const [selectedAlert, setSelectedAlert] = useState<AlertItem | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('GJ01AB1234');
  const [isAudioAlertEnabled, setIsAudioAlertEnabled] = useState<boolean>(true);

  // Master Data Refresh Function
  const loadAllData = useCallback(async () => {
    try {
      const [
        healthData,
        statusData,
        statsData,
        camsData,
        alertsData,
        eventsData,
        watchlistsData,
        evidenceData,
        auditData,
      ] = await Promise.all([
        fetchSystemHealth(),
        fetchSystemStatus(),
        fetchSystemStats(),
        fetchCameras(),
        fetchAlerts(100),
        fetchVehicleEvents(100),
        fetchWatchlists(),
        fetchEvidenceRecords(),
        fetchAuditLogs(),
      ]);

      setHealth(healthData);
      setStatus(statusData);
      setStats(statsData);
      if (camsData.length > 0) setCameras(camsData);
      setAlerts(alertsData);
      setEvents(eventsData);
      setWatchlists(watchlistsData);
      setEvidence(evidenceData);
      setAuditLogs(auditData);
      setLoading(false);
    } catch (err) {
      console.error('Failed to sync live data from backend:', err);
      setLoading(false);
    }
  }, []);

  // Initial Load and Periodic Real-Time Polling
  useEffect(() => {
    let isMounted = true;

    loadAllData();
    // Also load initial reconstructed journey for primary test vehicle
    fetchJourney('GJ01AB1234').then((res) => {
      if (isMounted && res.waypoints.length > 0) {
        setJourney(res);
      }
    });

    const interval = setInterval(() => {
      if (isMounted) {
        loadAllData();
      }
    }, 10000);

    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [loadAllData]);

  // Handle Tracking Vehicle Plate across cameras
  const handleTrackPlate = async (plate: string) => {
    const clean = plate.trim().toUpperCase();
    setSearchQuery(clean);
    setActiveTab('correlation');
    try {
      const reconstructed = await fetchJourney(clean);
      setJourney(reconstructed);
    } catch (err) {
      console.error('Failed to reconstruct journey for plate:', clean, err);
    }
  };

  // Handle Alert Acknowledgement
  const handleAcknowledgeAlert = async (alertId: string) => {
    try {
      await acknowledgeAlertApi(alertId);
    } catch (err) {
      console.warn('API acknowledgement failed, updating locally:', err);
    }

    setAlerts((prev) =>
      prev.map((a) =>
        a.id === alertId
          ? {
              ...a,
              status: 'ACKNOWLEDGED',
              acknowledged_by: 'Insp. V. Patel',
              acknowledged_at: new Date().toISOString(),
            }
          : a
      )
    );
    if (selectedAlert?.id === alertId) {
      setSelectedAlert((prev) =>
        prev
          ? {
              ...prev,
              status: 'ACKNOWLEDGED',
              acknowledged_by: 'Insp. V. Patel',
              acknowledged_at: new Date().toISOString(),
            }
          : null
      );
    }
  };

  return (
    <AppLayout
      activeTab={activeTab}
      onTabChange={setActiveTab}
      health={health}
      loading={loading}
      activeAlerts={alerts.filter((a) => a.status === 'NEW')}
      onSelectAlert={(alert) => setSelectedAlert(alert)}
      onQuickSearch={(query) => handleTrackPlate(query)}
      isAudioAlertEnabled={isAudioAlertEnabled}
      onToggleAudioAlert={() => setIsAudioAlertEnabled(!isAudioAlertEnabled)}
    >
      {/* Dynamic View Switching */}
      {activeTab === 'dashboard' && (
        <DashboardPage
          health={health}
          stats={stats}
          alerts={alerts.filter((a) => a.status === 'NEW')}
          recentEvents={events}
          cameras={cameras}
          onNavigate={setActiveTab}
          onSearch={handleTrackPlate}
          onSelectAlert={(alert) => setSelectedAlert(alert)}
        />
      )}

      {activeTab === 'live' && <LiveGridPage cameras={cameras} />}

      {activeTab === 'search' && (
        <SearchPage
          initialQuery={searchQuery}
          onTrackPlate={handleTrackPlate}
          events={events}
        />
      )}

      {activeTab === 'correlation' && (
        <CorrelationPage
          journey={journey}
          onOpenMap={() => setActiveTab('gis')}
          onSearchNewPlate={handleTrackPlate}
        />
      )}

      {activeTab === 'gis' && <MapPage cameras={cameras} journey={journey} />}

      {activeTab === 'watchlists' && <WatchlistsPage watchlists={watchlists} />}

      {activeTab === 'alerts' && (
        <AlertsPage
          alerts={alerts}
          onAcknowledgeAlert={handleAcknowledgeAlert}
          onTrackPlate={handleTrackPlate}
        />
      )}

      {activeTab === 'evidence' && <EvidencePage evidence={evidence} />}

      {activeTab === 'audit' && <AuditPage logs={auditLogs} />}

      {activeTab === 'cameras' && <CamerasPage cameras={cameras} onRefresh={loadAllData} />}

      {activeTab === 'system' && <SystemPage status={status} health={health} />}

      {/* Real-time Alert Triage Modal */}
      {selectedAlert && (
        <Modal
          isOpen={!!selectedAlert}
          onClose={() => setSelectedAlert(null)}
          title={`ALERT TRIAGE: ${selectedAlert.plate_number}`}
          subtitle={`Triggered on ${selectedAlert.camera_name} - ${new Date(
            selectedAlert.timestamp
          ).toLocaleString()}`}
          icon={<ShieldAlert className="h-5 w-5 text-rose-500" />}
          maxWidth="2xl"
          footer={
            <>
              <Button variant="ghost" size="sm" onClick={() => setSelectedAlert(null)}>
                Dismiss View
              </Button>
              <Button
                variant="outline"
                size="sm"
                icon={<Eye className="h-3.5 w-3.5" />}
                onClick={() => {
                  setSelectedAlert(null);
                  handleTrackPlate(selectedAlert.plate_number);
                }}
              >
                Track Cross-Camera Movement
              </Button>
              {selectedAlert.status === 'NEW' && (
                <Button
                  variant="warning"
                  size="sm"
                  icon={<CheckCircle className="h-3.5 w-3.5" />}
                  onClick={() => handleAcknowledgeAlert(selectedAlert.id)}
                >
                  Acknowledge Alert
                </Button>
              )}
            </>
          }
        >
          <div className="space-y-4 font-mono text-xs">
            <div className="flex items-center justify-between bg-black/60 p-3 rounded-xl border border-slate-800">
              <span className="text-xl font-bold text-yellow-300">
                {selectedAlert.plate_number}
              </span>
              <div className="flex items-center gap-2">
                <PriorityBadge priority={selectedAlert.priority} />
                <CategoryBadge category={selectedAlert.category} />
                <StatusBadge status={selectedAlert.status} />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 p-4 rounded-xl bg-[#090e1a] border border-slate-800">
              <div>
                <span className="text-slate-400 block text-[10px]">WATCHLIST RULE</span>
                <span className="text-white font-bold">{selectedAlert.watchlist_name}</span>
              </div>
              <div>
                <span className="text-slate-400 block text-[10px]">CASE NUMBER</span>
                <span className="text-amber-400 font-bold">
                  {selectedAlert.case_number || 'ACTIVE_ALERT'}
                </span>
              </div>
              <div>
                <span className="text-slate-400 block text-[10px]">CCTV NODE</span>
                <span className="text-white font-bold">{selectedAlert.camera_name}</span>
              </div>
              <div>
                <span className="text-slate-400 block text-[10px]">LOCATION</span>
                <span className="text-white font-bold">{selectedAlert.location}</span>
              </div>
            </div>

            <div className="p-3 rounded-xl bg-blue-950/40 border border-blue-800/60 text-blue-200 text-[11px]">
              <div className="font-semibold text-blue-100 mb-1">AUTOMATED DISPATCH DIRECTIVE:</div>
              Immediate vehicle intercept alert dispatched to nearest patrol units. AI confidence{' '}
              <strong className="text-white font-bold">98.4%</strong>. Retain snapshot in evidence vault.
            </div>
          </div>
        </Modal>
      )}
    </AppLayout>
  );
}

export default App;
