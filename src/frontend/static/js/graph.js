/* Graph visualization with vis-network */

let network = null;
let nodes = null;
let edges = null;

function channelColor(ch) {
  if (!ch) return "#6b7280";
  if (ch.startsWith("drives")) return "#60a5fa";
  if (ch.startsWith("inverse")) return "#f87171";
  if (ch.startsWith("correlates")) return "#34d399";
  if (ch.startsWith("sentiment")) return "#a78bfa";
  if (ch.startsWith("policy")) return "#fbbf24";
  if (ch.startsWith("liquidity")) return "#38bdf8";
  return "#9ca3af";
}

async function initGraph() {
  const data = await fetchJSON("/graph-data");
  nodes = new vis.DataSet(data.nodes);
  edges = new vis.DataSet(data.edges);

  const container = document.getElementById("graph-container");
  const options = {
    interaction: { hover: true, zoomView: true, dragView: true },
    nodes: { shape: "dot", font: { size: 10, color: "#e5e7eb" }, borderWidth: 2 },
    edges: { smooth: { type: "continuous" }, color: { color: "#475569" } },
    physics: {
      enabled: true,
      stabilization: { iterations: 140, fit: true },
      barnesHut: {
        gravitationalConstant: -2400,
        springLength: 120,
        springConstant: 0.004,
        avoidOverlap: 0.35
      }
    }
  };
  
  network = new vis.Network(container, { nodes, edges }, options);

  network.on("click", async (params) => {
    if (params.nodes && params.nodes.length) {
      const id = params.nodes[0];
      const d = await fetchJSON(`/node/${encodeURIComponent(id)}`);
      document.getElementById("detail_box").innerHTML =
        `<b>Node</b> ${d.node_id} · <span style="color:#a78bfa">${d.kind}</span><br/><b>${d.label}</b><br/>${d.description || ""}<br/><br/>Degree: ${d.degree} · Score: ${d.score.toFixed(2)}` +
        `<div style="margin-top:10px;"><b>Top connections</b><br/>` +
        d.edges.map(e => `• ${e.neighbor_label} — ${e.top_channel} (${e.weight.toFixed(2)})`).join("<br/>") + `</div>`;
    } else if (params.edges && params.edges.length) {
      const eid = params.edges[0];
      const d = await fetchJSON(`/edge/${eid}`);
      document.getElementById("detail_box").innerHTML =
        `<b>Edge</b> #${d.edge_id}<br/>${d.a_label} ⟷ ${d.b_label}<br/>weight=${d.weight.toFixed(2)} · top=${d.top_channel || ""}<br/><br/>` +
        `<b>Channels</b><br/>` +
        d.channels.map(c => `• <span style="color:${channelColor(c.channel)}">${c.channel}</span>: ${c.strength.toFixed(2)}`).join("<br/>");
    }
  });
}

async function refreshGraph() {
  const data = await fetchJSON("/graph-data");
  nodes.clear();
  edges.clear();
  nodes.add(data.nodes);
  edges.add(data.edges);
  if (network) {
    network.stabilize(60);
  }
}
