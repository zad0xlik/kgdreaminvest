/* Utility functions */

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts || {});
  return await r.json();
}

function toggleStarredPlansSection() {
  const content = document.getElementById("starred-plans-content");
  const icon = document.getElementById("starred-plans-expand-icon");
  
  if (content.classList.contains("expanded")) {
    content.classList.remove("expanded");
    icon.classList.add("collapsed");
  } else {
    content.classList.add("expanded");
    icon.classList.remove("collapsed");
  }
}

function toggleBellwethersSection() {
  const content = document.getElementById("bellwethers-content");
  const icon = document.getElementById("bellwethers-expand-icon");
  
  if (content.classList.contains("expanded")) {
    content.classList.remove("expanded");
    icon.classList.add("collapsed");
  } else {
    content.classList.add("expanded");
    icon.classList.remove("collapsed");
    refreshBellwethers();
  }
}

function toggleInvestiblesSection() {
  const content = document.getElementById("investibles-content");
  const icon = document.getElementById("investibles-expand-icon");
  
  if (content.classList.contains("expanded")) {
    content.classList.remove("expanded");
    icon.classList.add("collapsed");
  } else {
    content.classList.add("expanded");
    icon.classList.remove("collapsed");
    refreshInvestibles();
  }
}

function toggleStatsSection() {
  const content = document.getElementById("stats-content");
  const icon = document.getElementById("stats-expand-icon");
  
  if (content.classList.contains("expanded")) {
    content.classList.remove("expanded");
    icon.classList.add("collapsed");
  } else {
    content.classList.add("expanded");
    icon.classList.remove("collapsed");
    refreshStatsData();
  }
}

// Worker controls
async function marketStart() {
  await fetchJSON("/api/market/start", { method: "POST" });
  await refreshAll();
}

async function marketStop() {
  await fetchJSON("/api/market/stop", { method: "POST" });
  await refreshAll();
}

async function dreamStart() {
  await fetchJSON("/api/dream/start", { method: "POST" });
  await refreshAll();
}

async function dreamStop() {
  await fetchJSON("/api/dream/stop", { method: "POST" });
  await refreshAll();
}

async function thinkStart() {
  await fetchJSON("/api/think/start", { method: "POST" });
  await refreshAll();
}

async function thinkStop() {
  await fetchJSON("/api/think/stop", { method: "POST" });
  await refreshAll();
}

async function stepMarket() {
  await fetchJSON("/api/market/step", { method: "POST" });
  await refreshAll();
}

async function stepThink() {
  await fetchJSON("/api/think/step", { method: "POST" });
  await refreshAll();
}

async function approveInsight(id) {
  await fetchJSON(`/api/insight/${id}/approve`, { method: "POST" });
  await refreshAll();
}
