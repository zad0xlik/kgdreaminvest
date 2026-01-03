/* Main application logic - refreshing, configurations */

async function refreshAll() {
  const st = await fetchJSON("/api/state");
  
  // Update KPIs
  document.getElementById("k_nodes").textContent = st.nodes;
  document.getElementById("k_edges").textContent = st.edges;

  // Update bellwethers
  document.getElementById("bw_spy").textContent = st.latest.spy;
  document.getElementById("bw_qqq").textContent = st.latest.qqq;
  document.getElementById("bw_vix").textContent = st.latest.vix;
  document.getElementById("bw_uup").textContent = st.latest.uup;
  
  // Update snapshot timestamp with timezone conversion
  if (st.latest.timestamp) {
    const ts = convertToUserTimezone(st.latest.timestamp);
    const tzAbbr = getTimezoneAbbr();
    document.getElementById("snapshot_time").textContent = `Updated: ${ts} ${tzAbbr}`;
  }
  
  // Format and display signals as clean table
  const signals = st.latest.signals || {};
  const signalLabels = {
    'risk_off': 'Risk-Off',
    'rates_up': 'Rates Up',
    'oil_shock': 'Oil Shock',
    'semi_pulse': 'Semi Pulse'
  };
  
  let signalsHtml = '';
  for (const [key, value] of Object.entries(signals)) {
    const label = signalLabels[key] || key;
    const percentage = (value * 100).toFixed(1);
    signalsHtml += `<div class="row"><div class="label">${label}</div><div class="value">${percentage}%</div></div>`;
  }
  document.getElementById("signals_table").innerHTML = signalsHtml || '<div class="small" style="color:#9ca3af">No signals available</div>';

  // Update portfolio
  document.getElementById("pf_cash").textContent = st.portfolio.cash;
  document.getElementById("pf_equity").textContent = st.portfolio.equity;

  // Update LLM budget
  document.getElementById("llm_calls").textContent = `${st.llm.calls_used} / ${st.llm.calls_budget}`;
  document.getElementById("llm_err").textContent = st.llm.last_error || "";

  // Update worker badges
  const mk = document.getElementById("market_badge");
  mk.className = "pill " + (st.market_running ? "on" : "off");
  mk.textContent = st.market_running ? "ON" : "OFF";
  
  const dr = document.getElementById("dream_badge");
  dr.className = "pill " + (st.dream_running ? "on" : "off");
  dr.textContent = st.dream_running ? "ON" : "OFF";
  
  const th = document.getElementById("think_badge");
  th.className = "pill " + (st.think_running ? "on" : "off");
  th.textContent = st.think_running ? "ON" : "OFF";
  
  const tr = document.getElementById("trade_badge");
  tr.className = "pill " + (st.auto_trade ? "on" : "off");
  tr.textContent = st.auto_trade ? "ON" : "OFF";

  // Update positions table with both equities and options (with timezone conversion)
  document.querySelector("#pos_table tbody").innerHTML = st.portfolio.positions.map(p => {
    const typeClass = p.type === 'option' ? 'option-badge' : 'equity-badge';
    const typeLabel = p.type === 'option' ? 'OPT' : 'STK';
    const executionTime = p.updated_at ? convertToUserTimezone(p.updated_at, false) : '—';
    const qtyDisplay = p.type === 'option' ? p.qty.toFixed(0) : p.qty.toFixed(3);
    
    return `<tr>
      <td><span class="${typeClass}">${typeLabel}</span> ${p.symbol}</td>
      <td>${qtyDisplay}</td>
      <td>${p.last_price.toFixed(2)}</td>
      <td class="${p.pnl >= 0 ? 'positive' : 'negative'}">${p.pnl >= 0 ? '+' : ''}${p.pnl.toFixed(2)}</td>
      <td class="small">${executionTime}</td>
    </tr>`;
  }).join("");

  // Update logs (with timezone conversion)
  document.getElementById("log_box").innerHTML = st.logs.map(l => {
    const timestamp = convertToUserTimezone(l.ts);
    return `<div class="log"><b>${l.actor}</b> · <span style="color:#a78bfa">${l.action}</span><br/><span class="small">${timestamp}</span><br/>${l.detail || ""}</div>`;
  }).join("");

  // Update insights (with timezone conversion)
  document.getElementById("insight_box").innerHTML = st.insights.map(ins => {
    const timestamp = convertToUserTimezone(ins.ts);
    return `<div class="insight">
      <div class="title">${ins.title}</div>
      <div class="small">${timestamp} · status=${ins.status}</div>
      <div style="margin-top:8px; white-space:pre-wrap;">${ins.body}</div>
      <div class="action"><b>Decisions:</b> <span class="small mono">${ins.decisions}</span></div>
      <div class="meta">
        <span>★ ${ins.critic_score.toFixed(2)} · conf ${ins.confidence.toFixed(2)}</span>
        <span><button class="btn gray" style="width:auto;padding:6px 10px;margin:0" onclick="approveInsight(${ins.insight_id})">Approve</button></span>
      </div>
    </div>`;
  }).join("");

  // Refresh stats if expanded
  if (document.getElementById("stats-content").classList.contains("expanded")) {
    await refreshStatsData();
  }

  await refreshGraph();
}

async function refreshStatsData() {
  try {
    const stats = await fetchJSON("/api/stats");
    const history = await fetchJSON("/api/ticker-history?limit=20");
    
    document.getElementById("total-lookups").textContent = stats.lookup_stats.total_lookups;
    document.getElementById("success-rate").textContent = `${stats.lookup_stats.success_rate}%`;
    document.getElementById("recent-24h").textContent = stats.lookup_stats.recent_24h;
    document.getElementById("failed-lookups").textContent = stats.lookup_stats.failed_lookups;
    
    const topTickersHtml = stats.top_tickers.map(t => 
      `<div class="row" style="margin:2px 0"><div class="label">${t.ticker}</div><div class="value">${t.lookup_count} ($${t.avg_price})</div></div>`
    ).join("");
    document.getElementById("top-tickers").innerHTML = topTickersHtml || "No data yet";
    
    const historyHtml = history.history.map(h => {
      const statusClass = h.success ? "history-success" : "history-fail";
      const priceText = h.price ? `$${h.price} (${h.change_pct > 0 ? '+' : ''}${h.change_pct}%)` : "Failed";
      return `<div class="history-item ${statusClass}">
        <b>${h.ticker}</b> · ${h.ts}<br/>
        ${priceText}${h.volume ? ` · Vol: ${h.volume.toLocaleString()}` : ""}
      </div>`;
    }).join("");
    document.getElementById("ticker-history").innerHTML = historyHtml || "No history yet";
  } catch (e) {
    console.error("Error refreshing stats:", e);
    document.getElementById("top-tickers").textContent = "Error loading stats";
    document.getElementById("ticker-history").textContent = "Error loading history";
  }
}

async function refreshBellwethers() {
  try {
    const data = await fetchJSON("/api/bellwethers");
    
    const categoryColors = {
      'volatility': '#f59e0b', 'equity': '#10b981', 'bonds': '#3b82f6',
      'forex': '#8b5cf6', 'commodities': '#ef4444', 'rates': '#06b6d4',
      'semiconductors': '#ec4899', 'other': '#6b7280'
    };
    
    const bellwethersHtml = data.bellwethers.map(b => {
      const catColor = categoryColors[b.category] || categoryColors['other'];
      const toggleClass = b.enabled ? 'on' : 'off';
      return `<div class="row" style="margin:4px 0;padding:8px">
        <div style="display:flex;align-items:center;gap:8px;flex:1">
          <span class="pill ${toggleClass}" style="cursor:pointer;min-width:40px;text-align:center" onclick="toggleBellwether('${b.ticker}', ${b.enabled})">${b.enabled ? 'ON' : 'OFF'}</span>
          <b>${b.ticker}</b>
          <span style="color:${catColor};font-size:10px;text-transform:uppercase">${b.category}</span>
        </div>
        <button class="btn red" style="width:auto;padding:4px 8px;margin:0;font-size:10px" onclick="removeBellwether('${b.ticker}')">×</button>
      </div>`;
    }).join("");
    
    document.getElementById("bellwethers-list").innerHTML = bellwethersHtml || "No bellwethers configured";
  } catch (e) {
    console.error("Error refreshing bellwethers:", e);
    document.getElementById("bellwethers-list").textContent = "Error loading bellwethers";
  }
}

async function addBellwether() {
  const input = document.getElementById("new-bellwether-ticker");
  const ticker = input.value.trim().toUpperCase();
  
  if (!ticker) {
    alert("Please enter a ticker symbol");
    return;
  }
  
  try {
    const result = await fetchJSON("/api/bellwethers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: ticker, category: "other" })
    });
    
    if (result.success) {
      input.value = "";
      await refreshBellwethers();
    } else {
      alert(result.error || "Failed to add bellwether");
    }
  } catch (e) {
    alert("Error adding bellwether: " + e.message);
  }
}

async function toggleBellwether(ticker, currentState) {
  try {
    await fetchJSON(`/api/bellwethers/${ticker}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !currentState })
    });
    await refreshBellwethers();
  } catch (e) {
    alert("Error toggling bellwether: " + e.message);
  }
}

async function removeBellwether(ticker) {
  if (!confirm(`Remove bellwether ${ticker}?`)) return;
  
  try {
    await fetchJSON(`/api/bellwethers/${ticker}`, { method: "DELETE" });
    await refreshBellwethers();
  } catch (e) {
    alert("Error removing bellwether: " + e.message);
  }
}

async function refreshInvestibles() {
  try {
    const data = await fetchJSON("/api/investibles");
    
    const levelColors = { 0: '#10b981', 1: '#60a5fa', 2: '#a78bfa' };
    const levelLabels = { 0: 'USER', 1: 'SIMILAR', 2: 'DEPENDENT' };
    const sectorColors = {
      'Technology': '#ec4899', 'Healthcare': '#10b981', 'Financials': '#3b82f6',
      'Energy': '#f59e0b', 'Industrials': '#6366f1', 'Consumer Discretionary': '#8b5cf6',
      'Consumer Staples': '#14b8a6', 'Materials': '#84cc16', 'Real Estate': '#06b6d4',
      'Utilities': '#eab308', 'Communication Services': '#f97316'
    };
    
    const tree = data.tree || {};
    let investiblesHtml = '';
    
    const rootStocks = tree["null"] || tree[null] || [];
    if (rootStocks.length > 0) {
      rootStocks.forEach(inv => {
        const lvlColor = levelColors[inv.expansion_level] || '#6b7280';
        const sectorColor = sectorColors[inv.sector] || '#9ca3af';
        const toggleClass = inv.enabled ? 'on' : 'off';
        const lvlLabel = levelLabels[inv.expansion_level] || 'L' + inv.expansion_level;
        
        investiblesHtml += `<div style="margin:4px 0">
          <div class="row" style="padding:6px 8px;background:rgba(255,255,255,.04)">
            <div style="display:flex;align-items:center;gap:6px;flex:1">
              <span class="pill ${toggleClass}" style="cursor:pointer;min-width:35px;text-align:center;font-size:10px" onclick="toggleInvestible('${inv.ticker}', ${inv.enabled})">${inv.enabled ? 'ON' : 'OFF'}</span>
              <b style="color:${lvlColor}">${inv.ticker}</b>
              <span style="color:${lvlLabel === 'USER' ? lvlColor : '#9ca3af'};font-size:9px;font-weight:800">${lvlLabel}</span>
              ${inv.sector ? `<span style="color:${sectorColor};font-size:9px">${inv.sector}</span>` : ''}
            </div>
            <button class="btn red" style="width:auto;padding:3px 6px;margin:0;font-size:10px" onclick="removeInvestible('${inv.ticker}')">×</button>
          </div>`;
        
        // Render children
        if (tree[inv.ticker] && tree[inv.ticker].length > 0) {
          tree[inv.ticker].forEach(child => {
            const childLvlColor = levelColors[child.expansion_level] || '#6b7280';
            const childSectorColor = sectorColors[child.sector] || '#9ca3af';
            const childToggleClass = child.enabled ? 'on' : 'off';
            const childLvlLabel = levelLabels[child.expansion_level] || 'L' + child.expansion_level;
            
            investiblesHtml += `<div class="row" style="margin-left:20px;padding:5px 8px;background:rgba(255,255,255,.02);border-left:2px solid ${childLvlColor}">
              <div style="display:flex;align-items:center;gap:6px;flex:1">
                <span class="pill ${childToggleClass}" style="cursor:pointer;min-width:35px;text-align:center;font-size:9px" onclick="toggleInvestible('${child.ticker}', ${child.enabled})">${child.enabled ? 'ON' : 'OFF'}</span>
                <span style="color:${childLvlColor};font-size:11px">${child.ticker}</span>
                <span style="color:#9ca3af;font-size:8px;font-weight:800">${childLvlLabel}</span>
                ${child.sector ? `<span style="color:${childSectorColor};font-size:8px">${child.sector}</span>` : ''}
                ${child.notes ? `<span style="color:#9ca3af;font-size:8px" title="${child.notes}">ℹ️</span>` : ''}
              </div>
              <button class="btn red" style="width:auto;padding:2px 5px;margin:0;font-size:9px" onclick="removeInvestible('${child.ticker}')">×</button>
            </div>`;
            
            // Grandchildren
            if (tree[child.ticker] && tree[child.ticker].length > 0) {
              tree[child.ticker].forEach(grandchild => {
                const gcLvlColor = levelColors[grandchild.expansion_level] || '#6b7280';
                const gcSectorColor = sectorColors[grandchild.sector] || '#9ca3af';
                const gcToggleClass = grandchild.enabled ? 'on' : 'off';
                const gcLvlLabel = levelLabels[grandchild.expansion_level] || 'L' + grandchild.expansion_level;
                
                investiblesHtml += `<div class="row" style="margin-left:40px;padding:4px 6px;background:rgba(255,255,255,.01);border-left:2px solid ${gcLvlColor}">
                  <div style="display:flex;align-items:center;gap:4px;flex:1">
                    <span class="pill ${gcToggleClass}" style="cursor:pointer;min-width:30px;text-align:center;font-size:8px" onclick="toggleInvestible('${grandchild.ticker}', ${grandchild.enabled})">${grandchild.enabled ? 'ON' : 'OFF'}</span>
                    <span style="color:${gcLvlColor};font-size:10px">${grandchild.ticker}</span>
                    <span style="color:#9ca3af;font-size:7px;font-weight:800">${gcLvlLabel}</span>
                    ${grandchild.sector ? `<span style="color:${gcSectorColor};font-size:7px">${grandchild.sector}</span>` : ''}
                  </div>
                  <button class="btn red" style="width:auto;padding:2px 4px;margin:0;font-size:8px" onclick="removeInvestible('${grandchild.ticker}')">×</button>
                </div>`;
              });
            }
          });
        }
        investiblesHtml += `</div>`;
      });
    }
    
    document.getElementById("investibles-list").innerHTML = investiblesHtml || "No investibles configured";
    
    const status = await fetchJSON("/api/investibles/expansion-status");
    if (status.expansion && status.expansion.is_running) {
      document.getElementById("expansion-status").style.display = "block";
      document.getElementById("expansion-progress").textContent = 
        `Expanding from ${status.expansion.current_ticker}: ${status.expansion.progress}/${status.expansion.total} stocks added`;
    } else {
      document.getElementById("expansion-status").style.display = "none";
    }
  } catch (e) {
    console.error("Error refreshing investibles:", e);
    document.getElementById("investibles-list").textContent = "Error loading investibles";
  }
}

async function addInvestible() {
  const input = document.getElementById("new-investible-ticker");
  const ticker = input.value.trim().toUpperCase();
  const autoExpand = document.getElementById("auto-expand-checkbox").checked;
  
  if (!ticker) {
    alert("Please enter a ticker symbol");
    return;
  }
  
  try {
    const result = await fetchJSON("/api/investibles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: ticker, auto_expand: autoExpand })
    });
    
    if (result.success) {
      input.value = "";
      await refreshInvestibles();
      
      if (result.expansion_started) {
        setTimeout(() => refreshInvestibles(), 2000);
        setInterval(() => {
          if (document.getElementById("investibles-content").classList.contains("expanded")) {
            refreshInvestibles();
          }
        }, 3000);
      }
    } else {
      alert(result.error || "Failed to add investible");
    }
  } catch (e) {
    alert("Error adding investible: " + e.message);
  }
}

async function toggleInvestible(ticker, currentState) {
  try {
    await fetchJSON(`/api/investibles/${ticker}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !currentState })
    });
    await refreshInvestibles();
  } catch (e) {
    alert("Error toggling investible: " + e.message);
  }
}

async function removeInvestible(ticker) {
  if (!confirm(`Remove investible ${ticker}?`)) return;
  
  try {
    await fetchJSON(`/api/investibles/${ticker}`, { method: "DELETE" });
    await refreshInvestibles();
  } catch (e) {
    alert("Error removing investible: " + e.message);
  }
}

// Initialize app
async function initApp() {
  // Initialize timezone selector from localStorage
  const savedTimezone = getUserTimezone();
  const timezoneSelector = document.getElementById('timezone_selector');
  if (timezoneSelector) {
    timezoneSelector.value = savedTimezone;
  }
  
  await initGraph();
  await refreshAll();
  setInterval(refreshAll, 7000);
}

// Tab switching
function switchTab(tabName) {
  // Hide all tabs
  document.querySelectorAll('.tab-content').forEach(tab => {
    tab.classList.remove('active');
  });
  
  // Deactivate all tab buttons
  document.querySelectorAll('.tab-button').forEach(btn => {
    btn.classList.remove('active');
  });
  
  // Show selected tab
  document.getElementById(`tab-${tabName}`).classList.add('active');
  document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
  
  // Load tab-specific content
  if (tabName === 'prompts') {
    loadPromptsEditor();
  } else if (tabName === 'transactions') {
    loadTransactions();
  }
}

// Start when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
