import { useState, useEffect, useCallback } from 'react';
import { ReactFlow, Background, Controls } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import AlertPanel from './AlertPanel';

const GRAPH_STATUS_URL = "https://func-refinery-cascade.azurewebsites.net/api/graphstatus";

// How often to re-fetch the graph, in milliseconds.
const POLL_INTERVAL_MS = 3000;

// --- Layout ---
// The switch mesh isn't tiered like the old tree topology, so nodes are
// placed evenly around a circle instead of hardcoded per-node. Twin IDs
// are sorted first so node order (and therefore position) stays stable
// across polls regardless of what order the API returns them in.
function computeCircularLayout(twinIds, { radius = 280, centerX = 400, centerY = 320 } = {}) {
  const sortedIds = [...twinIds].sort();
  const positions = {};
  sortedIds.forEach((id, i) => {
    const angle = (2 * Math.PI * i) / sortedIds.length - Math.PI / 2; // start at top, go clockwise
    positions[id] = {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    };
  });
  return positions;
}

function colorForStatus(status) {
  if (status === "online") return "#2e7d32";
  if (status === "unreachable") return "#c62828";
  return "gray";
}

function edgeStyleForLinkStatus(linkStatus) {
  if (linkStatus === "down") {
    return { stroke: "#c62828", strokeWidth: 2, strokeDasharray: "5,5" };
  }
  return { stroke: "#888", strokeWidth: 2 };
}

// Every mesh link exists as two directed relationships (A->B and B->A --
// see seed_graph.py). Rendering both would draw the same line twice, so
// only the alphabetically-first direction is kept.
function transformGraphData(apiData) {
  const positions = computeCircularLayout(apiData.twins.map((t) => t.$dtId));

  const nodes = apiData.twins.map((twin) => ({
    id: twin.$dtId,
    position: positions[twin.$dtId] || { x: 0, y: 0 },
    data: { label: `${twin.isGateway ? "★ " : ""}${twin.$dtId}\n${twin.status}` },
    style: {
      backgroundColor: colorForStatus(twin.status),
      color: "white",
      padding: 10,
      borderRadius: 6,
      whiteSpace: "pre-line",
      textAlign: "center",
      border: twin.isGateway ? "3px solid #42a5f5" : "1px solid transparent",
    },
  }));

  const edges = apiData.relationships
    .filter((rel) => rel.$sourceId < rel.$targetId)
    .map((rel) => ({
      id: `${rel.$sourceId}--${rel.$targetId}`,
      source: rel.$sourceId,
      target: rel.$targetId,
      style: edgeStyleForLinkStatus(rel.linkStatus),
    }));

  return { nodes, edges };
}

function App() {
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [error, setError] = useState(null);

  const fetchGraphData = useCallback(async () => {
    try {
      const response = await fetch(GRAPH_STATUS_URL);
      if (!response.ok) {
        throw new Error(`Request failed: ${response.status}`);
      }
      const apiData = await response.json();
      const { nodes: newNodes, edges: newEdges } = transformGraphData(apiData);
      setNodes(newNodes);
      setEdges(newEdges);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    fetchGraphData();
    const intervalId = setInterval(fetchGraphData, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchGraphData]);

  return (
    <div style={{ position: "fixed", inset: 0 }}>
      {error && (
        <div style={{ color: "red", padding: 10 }}>
          Error fetching graph: {error}
        </div>
      )}
      <ReactFlow nodes={nodes} edges={edges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
      <AlertPanel />
    </div>
  );
}

export default App;
