/* Positions tab logic - Real-time broker position display */

let positionsRefreshInterval = null;
let currentSortColumn = 'symbol';
let currentSortDirection = 'asc';

/**
 * Load positions data and render the positions tab
 */
async function loadPositions() {
  try {
    const data = await fetchJSON("/api/positions");
    
    if (data.error) {
      showPositionsError(data.error);
      return;
    }
    
    renderPositionsSummary(data);
    renderPositionsTable(data);
    
    // Start auto-refresh if not already running
    if (!positionsRefreshInterval) {
      positionsRefreshInterval = setInterval(() => {
        // Only refresh if the positions tab is active
        if (document.getElementById('tab-positions').classList.contains('active')) {
          loadPositions();
        }
      }, 30000); // 30 seconds
    }
    
  } catch (error) {
    console.error("Error loading positions:", error);
    showPositionsError(error.message);
  }
}

/**
 * Show error message in positions tab
 */
function showPositionsError(errorMsg) {
  const content = document.getElementById('positions-content');
  content.innerHTML = `
    <div style="text-align:center;padding:40px;color:#ef4444">
      <div style="font-size:48px;margin-bottom:16px">⚠️</div>
      <div style="font-size:18px;font-weight:600;margin-bottom:8px">Error Loading Positions</div>
      <div style="color:#9ca3af">${errorMsg}</div>
      <button class="btn" style="margin-top:20px" onclick="loadPositions()">🔄 Retry</button>
    </div>
  `;
}

/**
 * Render account summary cards at the top
 */
function renderPositionsSummary(data) {
  const { account, total_positions, provider } = data;
  
  const providerLabel = provider === 'alpaca' ? '🏦 Alpaca' : '📄 Paper';
  const dailyPlClass = account.daily_pl >= 0 ? 'positive' : 'negative';
  const dailyPlSign = account.daily_pl >= 0 ? '+' : '';
  
  const summaryHTML = `
    <div class="positions-header">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px">
        <h2 style="margin:0;color:#e5e7eb;font-size:20px">${providerLabel} Positions</h2>
        <div style="display:flex;gap:10px">
          <button class="btn gray" onclick="loadPositions()" style="width:auto;padding:8px 16px;margin:0">
            🔄 Refresh
          </button>
        </div>
      </div>
      
      <div class="summary-cards">
        <div class="summary-card">
          <div class="summary-label">Account Value</div>
          <div class="summary-value">$${account.portfolio_value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
        </div>
        
        <div class="summary-card">
          <div class="summary-label">Cash Available</div>
          <div class="summary-value">$${account.cash.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
        </div>
        
        <div class="summary-card">
          <div class="summary-label">Buying Power</div>
          <div class="summary-value">$${account.buying_power.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
        </div>
        
        <div class="summary-card">
          <div class="summary-label">Day's P&L</div>
          <div class="summary-value ${dailyPlClass}">${dailyPlSign}$${Math.abs(account.daily_pl).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
          <div class="summary-sublabel ${dailyPlClass}">${dailyPlSign}${account.daily_pl_pct.toFixed(2)}%</div>
        </div>
        
        <div class="summary-card">
          <div class="summary-label">Total Positions</div>
          <div class="summary-value">${total_positions}</div>
        </div>
      </div>
    </div>
  `;
  
  // Update content
  const content = document.getElementById('positions-content');
  
  // Check if header already exists
  let headerDiv = content.querySelector('.positions-header');
  if (headerDiv) {
    // Update existing header
    headerDiv.outerHTML = summaryHTML;
  } else {
    // First load - clear everything and add header
    content.innerHTML = summaryHTML;
  }
}

/**
 * Render positions table with sortable columns
 */
function renderPositionsTable(data) {
  const { positions } = data;
  
  if (positions.length === 0) {
    const tableHTML = `
      <div style="margin-top:24px">
        <h3 style="margin:0 0 12px 0;color:#e5e7eb;font-size:16px">Open Positions</h3>
        <div style="text-align:center;padding:40px;background:rgba(0,0,0,.3);border-radius:12px;border:1px solid rgba(255,255,255,.08)">
          <div style="font-size:48px;margin-bottom:16px;opacity:0.5">📭</div>
          <div style="color:#9ca3af">No open positions</div>
        </div>
      </div>
    `;
    
    // Append to content
    const content = document.getElementById('positions-content');
    let tableContainer = content.querySelector('.positions-table-container');
    if (tableContainer) {
      tableContainer.outerHTML = tableHTML;
    } else {
      content.innerHTML += tableHTML;
    }
    return;
  }
  
  // Sort positions
  const sortedPositions = [...positions].sort((a, b) => {
    let aVal = a[currentSortColumn];
    let bVal = b[currentSortColumn];
    
    // Handle numeric vs string sorting
    if (typeof aVal === 'number' && typeof bVal === 'number') {
      return currentSortDirection === 'asc' ? aVal - bVal : bVal - aVal;
    } else {
      aVal = String(aVal).toLowerCase();
      bVal = String(bVal).toLowerCase();
      if (currentSortDirection === 'asc') {
        return aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
      } else {
        return aVal > bVal ? -1 : aVal < bVal ? 1 : 0;
      }
    }
  });
  
  // Generate table rows
  const rowsHTML = sortedPositions.map(pos => {
    const plClass = pos.unrealized_pl >= 0 ? 'positive' : 'negative';
    const plSign = pos.unrealized_pl >= 0 ? '+' : '';
    const plpcSign = pos.unrealized_plpc >= 0 ? '+' : '';
    const sideClass = pos.side === 'long' ? 'long-badge' : 'short-badge';
    
    return `
      <tr class="position-row">
        <td><b>${pos.symbol}</b></td>
        <td><span class="pill ${sideClass}">${pos.side.toUpperCase()}</span></td>
        <td>${pos.qty.toFixed(3)}</td>
        <td>$${pos.avg_entry_price.toFixed(2)}</td>
        <td>$${pos.current_price.toFixed(2)}</td>
        <td>$${pos.market_value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
        <td>$${pos.cost_basis.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
        <td class="${plClass}">${plSign}$${Math.abs(pos.unrealized_pl).toFixed(2)}</td>
        <td class="${plClass}">${plpcSign}${pos.unrealized_plpc.toFixed(2)}%</td>
        <td>
          <button class="btn gray" style="width:auto;padding:4px 8px;margin:0;font-size:11px" 
                  onclick="showPositionDetails('${pos.symbol}')" title="View details">
            👁️
          </button>
        </td>
      </tr>
    `;
  }).join('');
  
  const getSortIcon = (column) => {
    if (currentSortColumn === column) {
      return currentSortDirection === 'asc' ? ' ▲' : ' ▼';
    }
    return '';
  };
  
  const tableHTML = `
    <div class="positions-table-container" style="margin-top:24px">
      <h3 style="margin:0 0 12px 0;color:#e5e7eb;font-size:16px">Open Positions (${positions.length})</h3>
      <div style="overflow-x:auto">
        <table class="positions-table">
          <thead>
            <tr>
              <th onclick="sortPositionsTable('symbol')" style="cursor:pointer">Symbol${getSortIcon('symbol')}</th>
              <th onclick="sortPositionsTable('side')" style="cursor:pointer">Side${getSortIcon('side')}</th>
              <th onclick="sortPositionsTable('qty')" style="cursor:pointer">Quantity${getSortIcon('qty')}</th>
              <th onclick="sortPositionsTable('avg_entry_price')" style="cursor:pointer">Entry Price${getSortIcon('avg_entry_price')}</th>
              <th onclick="sortPositionsTable('current_price')" style="cursor:pointer">Current Price${getSortIcon('current_price')}</th>
              <th onclick="sortPositionsTable('market_value')" style="cursor:pointer">Market Value${getSortIcon('market_value')}</th>
              <th onclick="sortPositionsTable('cost_basis')" style="cursor:pointer">Cost Basis${getSortIcon('cost_basis')}</th>
              <th onclick="sortPositionsTable('unrealized_pl')" style="cursor:pointer">Unrealized P&L${getSortIcon('unrealized_pl')}</th>
              <th onclick="sortPositionsTable('unrealized_plpc')" style="cursor:pointer">P&L %${getSortIcon('unrealized_plpc')}</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            ${rowsHTML}
          </tbody>
        </table>
      </div>
    </div>
  `;
  
  // Update content
  const content = document.getElementById('positions-content');
  let tableContainer = content.querySelector('.positions-table-container');
  if (tableContainer) {
    tableContainer.outerHTML = tableHTML;
  } else {
    content.innerHTML += tableHTML;
  }
}

/**
 * Sort positions table by column
 */
function sortPositionsTable(column) {
  if (currentSortColumn === column) {
    // Toggle direction
    currentSortDirection = currentSortDirection === 'asc' ? 'desc' : 'asc';
  } else {
    // New column, default to ascending
    currentSortColumn = column;
    currentSortDirection = 'asc';
  }
  
  // Re-render table with new sort
  loadPositions();
}

/**
 * Show detailed view of a position
 */
async function showPositionDetails(symbol) {
  try {
    const data = await fetchJSON("/api/positions");
    const position = data.positions.find(p => p.symbol === symbol);
    
    if (!position) {
      alert(`Position ${symbol} not found`);
      return;
    }
    
    const plClass = position.unrealized_pl >= 0 ? 'positive' : 'negative';
    const plSign = position.unrealized_pl >= 0 ? '+' : '';
    const plpcSign = position.unrealized_plpc >= 0 ? '+' : '';
    
    const detailHTML = `
      <div style="padding:20px">
        <h3 style="margin:0 0 16px 0;color:#e5e7eb">${position.symbol} Position Details</h3>
        
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:20px">
          <div class="detail-item">
            <div class="detail-label">Side</div>
            <div class="detail-value">${position.side.toUpperCase()}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Asset Class</div>
            <div class="detail-value">${position.asset_class}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Quantity</div>
            <div class="detail-value">${position.qty.toFixed(3)}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Available</div>
            <div class="detail-value">${position.qty_available.toFixed(3)}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Entry Price</div>
            <div class="detail-value">$${position.avg_entry_price.toFixed(2)}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Current Price</div>
            <div class="detail-value">$${position.current_price.toFixed(2)}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Market Value</div>
            <div class="detail-value">$${position.market_value.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Cost Basis</div>
            <div class="detail-value">$${position.cost_basis.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Unrealized P&L</div>
            <div class="detail-value ${plClass}">${plSign}$${Math.abs(position.unrealized_pl).toFixed(2)}</div>
          </div>
          
          <div class="detail-item">
            <div class="detail-label">Unrealized P&L %</div>
            <div class="detail-value ${plClass}">${plpcSign}${position.unrealized_plpc.toFixed(2)}%</div>
          </div>
        </div>
        
        <div style="display:flex;gap:10px;justify-content:flex-end">
          <button class="btn gray" onclick="closeModal()">Close</button>
        </div>
      </div>
    `;
    
    showModal(detailHTML);
    
  } catch (error) {
    console.error("Error loading position details:", error);
    alert("Error loading position details: " + error.message);
  }
}

/**
 * Show modal dialog
 */
function showModal(content) {
  // Create modal if it doesn't exist
  let modal = document.getElementById('positions-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'positions-modal';
    modal.className = 'modal';
    modal.innerHTML = `
      <div class="modal-backdrop" onclick="closeModal()"></div>
      <div class="modal-content"></div>
    `;
    document.body.appendChild(modal);
  }
  
  // Update content
  modal.querySelector('.modal-content').innerHTML = content;
  modal.style.display = 'block';
}

/**
 * Close modal dialog
 */
function closeModal() {
  const modal = document.getElementById('positions-modal');
  if (modal) {
    modal.style.display = 'none';
  }
}

/**
 * Stop auto-refresh when leaving positions tab
 */
function stopPositionsRefresh() {
  if (positionsRefreshInterval) {
    clearInterval(positionsRefreshInterval);
    positionsRefreshInterval = null;
  }
}

// Export functions for use in app.js
window.loadPositions = loadPositions;
window.stopPositionsRefresh = stopPositionsRefresh;
window.sortPositionsTable = sortPositionsTable;
window.showPositionDetails = showPositionDetails;
window.closeModal = closeModal;
