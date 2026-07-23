import { useState, useEffect, useCallback } from 'react';

const ALERT_HISTORY_URL = "https://func-refinery-cascade.azurewebsites.net/api/alerthistory?limit=20";
const POLL_INTERVAL_MS = 5000;

function colorForEventType(eventType) {
  if (eventType === "unreachable") return "#c62828";
  if (eventType === "recovered") return "#2e7d32";
  return "#888";
}

function formatTimestamp(isoString) {
  return new Date(isoString).toLocaleTimeString();
}

function AlertPanel() {
  const [alerts, setAlerts] = useState([]);
  const [error, setError] = useState(null);

  const fetchAlerts = useCallback(async () => {
    try {
      const response = await fetch(ALERT_HISTORY_URL);
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      setAlerts(await response.json());
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchAlerts();
    const intervalId = setInterval(fetchAlerts, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchAlerts]);

  return (
    <div
      style={{
        position: "absolute",
        top: 10,
        right: 10,
        width: 300,
        maxHeight: "80vh",
        overflowY: "auto",
        background: "rgba(20, 20, 20, 0.9)",
        color: "white",
        borderRadius: 8,
        padding: 12,
        fontFamily: "monospace",
        fontSize: 13,
        zIndex: 10,
      }}
    >
      <div style={{ fontWeight: "bold", marginBottom: 8 }}>Alert History</div>
      {error && <div style={{ color: "#c62828" }}>Error: {error}</div>}
      {alerts.length === 0 && !error && <div style={{ color: "#888" }}>No alerts yet.</div>}
      {alerts.map((alert, i) => (
        <div
          key={`${alert.switch_id}-${alert.detected_at}-${i}`}
          style={{
            borderLeft: `3px solid ${colorForEventType(alert.event_type)}`,
            paddingLeft: 8,
            marginBottom: 6,
          }}
        >
          <div>{alert.switch_id}</div>
          <div style={{ color: colorForEventType(alert.event_type) }}>
            {alert.event_type} <span style={{ color: "#888" }}>{formatTimestamp(alert.detected_at)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default AlertPanel;
