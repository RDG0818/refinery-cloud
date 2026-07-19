import { useState, useEffect, useCallback } from 'react';
import { ReactFlow, Background, Controls } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

// TODO: paste your deployed Function App's URL here.
// Find it with: az functionapp show --name func-refinery-cascade
//   --resource-group rg-refinery-blastradius --query defaultHostName -o tsv
// Then it's https://<that>/api/GraphStatus
const GRAPH_STATUS_URL = "https://func-refinery-cascade.azurewebsites.net/api/graphstatus";

// How often to re-fetch the graph, in milliseconds. 3000 = every 3 seconds.
// Worth remembering the cost conversation from earlier -- don't set this
// so low that it's hammering ADT unnecessarily. A few seconds is plenty
// for a demo.
const POLL_INTERVAL_MS = 3000;

// --- Layout ---
// React Flow needs an explicit x/y pixel position for every node -- it
// doesn't know your graph is "3 tiers" on its own. Since our topology is
// small and fixed, we just hardcode positions rather than pulling in an
// auto-layout library (that'd be overkill for 7 nodes).
// Feel free to adjust these numbers once you see it rendered -- it's
// just trial and error to get spacing you like.
const NODE_POSITIONS = {
  "Compressor-01": { x: 300, y: 0 },
  "Pump-01": { x: 100, y: 150 },
  "Pump-02": { x: 500, y: 150 },
  "Sensor-01": { x: 0, y: 300 },
  "Sensor-02": { x: 200, y: 300 },
  "Sensor-03": { x: 400, y: 300 },
  "Sensor-04": { x: 600, y: 300 },
};

// TODO: this is the one piece of actual logic to write. Given a twin's
// status string ("online", "offline", "unreachable"), return a CSS
// color string. This is what makes the graph visually communicate the
// cascade -- healthy nodes one color, the failed source another, the
// cascaded victims a third.
//
// Suggestion: green for "online", red for "offline" (the actual failed
// device), orange or a muted red for "unreachable" (collateral damage --
// visually distinct from the root cause is a nice touch).
function colorForStatus(status) {
  if (status === "online") {
    return "green"; 
  }
  else if (status === "offline") {
    return "red";
  }
  else if (status === "unreachable") {
    return "orange";
  }
  return "gray";
}

// This function is the actual translation layer: it takes the raw JSON
// your GraphStatus endpoint returns and converts it into the exact shape
// React Flow expects -- an array of "nodes" and an array of "edges".
// This is a plain JS function, nothing React-specific about it.
function transformGraphData(apiData) {
  const nodes = apiData.twins.map((twin) => ({
    id: twin.$dtId,
    position: NODE_POSITIONS[twin.$dtId] || { x: 0, y: 0 },
    data: { label: `${twin.$dtId}\n${twin.status}` },
    style: {
      backgroundColor: colorForStatus(twin.status),
      color: "white",
      padding: 10,
      borderRadius: 6,
      whiteSpace: "pre-line",   // renders the \n in the label as a line break
      textAlign: "center",
    },
  }));

  const edges = apiData.relationships.map((rel) => ({
    id: rel.$relationshipId,
    source: rel.$sourceId,
    target: rel.$targetId,
  }));

  return { nodes, edges };
}

function App() {
  // React state: these two variables hold the current nodes/edges to
  // render. Calling setNodes/setEdges is what triggers React to
  // re-render the component with the new data -- you never mutate
  // these arrays directly, you always call the setter with a new value.
  const [nodes, setNodes] = useState([]);
  const [edges, setEdges] = useState([]);
  const [error, setError] = useState(null);

  // The actual fetch logic, wrapped in useCallback so it doesn't get
  // recreated every render (a React performance detail -- not critical
  // to understand deeply right now, just a common pattern you'll see
  // a lot).
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

  // useEffect runs side effects -- here, "fetch data, then keep fetching
  // on an interval." The empty array [] at the end means "run this setup
  // once, when the component first mounts" (as opposed to on every
  // render). setInterval schedules fetchGraphData to run repeatedly;
  // the returned cleanup function (clearInterval) stops that interval
  // if the component ever unmounts, which prevents a memory leak.
  useEffect(() => {
    fetchGraphData();
    const intervalId = setInterval(fetchGraphData, POLL_INTERVAL_MS);
    return () => clearInterval(intervalId);
  }, [fetchGraphData]);

  return (
    <div style={{ width: "100vw", height: "100vh" }}>
      {error && (
        <div style={{ color: "red", padding: 10 }}>
          Error fetching graph: {error}
        </div>
      )}
      <ReactFlow nodes={nodes} edges={edges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}

export default App;