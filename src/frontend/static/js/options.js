/**
 * Options Tab - Display and manage monitored options
 */

let optionsData = null;
let optionsRefreshTimer = null;
let sortColumn = 'underlying';
let sortAscending = true;
let filterUnderlying = '';
let filterType = '';

/**
 * Load options data from the API
 */
async function loadOptionsData() {
    try {
        const resp = await fetch('/api/options');
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        optionsData = await resp.json();
        renderOptionsTab();
    } catch (err) {
        console.error('Failed to load options data:', err);
        document.getElementById('options-content').innerHTML = 
            '<div class="error">Failed to load options data. Check console for details.</div>';
    }
}

/**
 * Render the options tab with current data
 */
function renderOptionsTab() {
    if (!optionsData) {
        document.getElementById('options-content').innerHTML = '<div>Loading...</div>';
        return;
    }
    
    const container = document.getElementById('options-content');
    
    // Summary cards at the top
    const summary = `
        <div class="options-summary">
            <div class="summary-card">
                <div class="summary-value">${optionsData.monitored_count}</div>
                <div class="summary-label">Monitored Options</div>
            </div>
            <div class="summary-card">
                <div class="summary-value">
                    <span class="pill ${optionsData.worker_running ? 'on' : 'off'}">
                        ${optionsData.worker_running ? 'ON' : 'OFF'}
                    </span>
                </div>
                <div class="summary-label">Options Worker</div>
            </div>
            <div class="summary-card greeks-card">
                <div class="summary-label">Portfolio Greeks</div>
                <div class="greeks-grid">
                    <div class="greek-item">
                        <span class="greek-label">Δ</span>
                        <span class="greek-value ${optionsData.aggregate_greeks.delta >= 0 ? 'positive' : 'negative'}">
                            ${optionsData.aggregate_greeks.delta.toFixed(2)}
                        </span>
                    </div>
                    <div class="greek-item">
                        <span class="greek-label">Γ</span>
                        <span class="greek-value">${optionsData.aggregate_greeks.gamma.toFixed(3)}</span>
                    </div>
                    <div class="greek-item">
                        <span class="greek-label">Θ</span>
                        <span class="greek-value ${optionsData.aggregate_greeks.theta >= 0 ? 'positive' : 'negative'}">
                            ${optionsData.aggregate_greeks.theta.toFixed(2)}
                        </span>
                    </div>
                    <div class="greek-item">
                        <span class="greek-label">V</span>
                        <span class="greek-value">${optionsData.aggregate_greeks.vega.toFixed(2)}</span>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Filters
    const uniqueUnderlyings = [...new Set(optionsData.options.map(o => o.underlying))].sort();
    const filters = `
        <div class="options-filters">
            <select id="filter-underlying" onchange="applyFilters()">
                <option value="">All Underlyings</option>
                ${uniqueUnderlyings.map(u => `<option value="${u}" ${filterUnderlying === u ? 'selected' : ''}>${u}</option>`).join('')}
            </select>
            <select id="filter-type" onchange="applyFilters()">
                <option value="">All Types</option>
                <option value="Call" ${filterType === 'Call' ? 'selected' : ''}>Calls</option>
                <option value="Put" ${filterType === 'Put' ? 'selected' : ''}>Puts</option>
            </select>
            <button class="btn gray" style="padding:8px 12px;margin:0 0 0 auto" onclick="loadOptionsData()">🔄 Refresh</button>
        </div>
    `;
    
    // Filter and sort options
    let displayOptions = optionsData.options.filter(o => {
        if (filterUnderlying && o.underlying !== filterUnderlying) return false;
        if (filterType && o.type !== filterType) return false;
        return true;
    });
    
    // Sort
    displayOptions.sort((a, b) => {
        let aVal = a[sortColumn];
        let bVal = b[sortColumn];
        if (typeof aVal === 'string') {
            aVal = aVal.toLowerCase();
            bVal = bVal.toLowerCase();
        }
        if (aVal < bVal) return sortAscending ? -1 : 1;
        if (aVal > bVal) return sortAscending ? 1 : -1;
        return 0;
    });
    
    // Options table
    const table = `
        <div class="options-table-container">
            <table class="options-table">
                <thead>
                    <tr>
                        <th onclick="sortBy('underlying')">Underlying ${sortColumn === 'underlying' ? (sortAscending ? '▲' : '▼') : ''}</th>
                        <th onclick="sortBy('type')">Type ${sortColumn === 'type' ? (sortAscending ? '▲' : '▼') : ''}</th>
                        <th onclick="sortBy('strike')">Strike ${sortColumn === 'strike' ? (sortAscending ? '▲' : '▼') : ''}</th>
                        <th onclick="sortBy('expiration')">Expiration ${sortColumn === 'expiration' ? (sortAscending ? '▲' : '▼') : ''}</th>
                        <th onclick="sortBy('last_price')">Price ${sortColumn === 'last_price' ? (sortAscending ? '▲' : '▼') : ''}</th>
                        <th>Greeks</th>
                        <th onclick="sortBy('volume')">Volume ${sortColumn === 'volume' ? (sortAscending ? '▲' : '▼') : ''}</th>
                        <th onclick="sortBy('open_interest')">OI ${sortColumn === 'open_interest' ? (sortAscending ? '▲' : '▼') : ''}</th>
                        <th>IV</th>
                        <th onclick="sortBy('executed')">Status ${sortColumn === 'executed' ? (sortAscending ? '▲' : '▼') : ''}</th>
                    </tr>
                </thead>
                <tbody>
                    ${displayOptions.length === 0 ? 
                        '<tr><td colspan="9" style="text-align:center;padding:20px;color:#9ca3af">No options match filters</td></tr>' :
                        displayOptions.map(opt => renderOptionRow(opt)).join('')
                    }
                </tbody>
            </table>
        </div>
    `;
    
    container.innerHTML = summary + filters + table;
}

/**
 * Render a single option row
 */
function renderOptionRow(opt) {
    const moneynessClass = opt.moneyness.toLowerCase();
    const typeClass = opt.type.toLowerCase();
    
    return `
        <tr class="option-row" onclick="showOptionDetails(${opt.option_id})" data-option-id="${opt.option_id}">
            <td><strong>${opt.underlying}</strong><br/><span class="small">$${opt.spot_price.toFixed(2)}</span></td>
            <td>
                <span class="option-type-badge ${typeClass}">${opt.type}</span>
                <span class="moneyness-badge ${moneynessClass}">${opt.moneyness}</span>
            </td>
            <td>$${opt.strike.toFixed(2)}</td>
            <td>
                ${opt.expiration}
                <br/><span class="small">${opt.dte} DTE</span>
            </td>
            <td>
                <strong>$${opt.last_price.toFixed(2)}</strong>
                <br/><span class="small">$${opt.bid.toFixed(2)} / $${opt.ask.toFixed(2)}</span>
            </td>
            <td class="greeks-cell">
                <div class="greeks-mini">
                    <span class="${opt.delta >= 0 ? 'positive' : 'negative'}">Δ ${opt.delta.toFixed(2)}</span>
                    <span>Γ ${opt.gamma.toFixed(3)}</span>
                    <span class="${opt.theta >= 0 ? 'positive' : 'negative'}">Θ ${opt.theta.toFixed(2)}</span>
                    <span>V ${opt.vega.toFixed(2)}</span>
                </div>
            </td>
            <td>${opt.volume.toLocaleString()}</td>
            <td>${opt.open_interest.toLocaleString()}</td>
            <td>${(opt.iv * 100).toFixed(1)}%</td>
            <td>
                ${opt.executed ? 
                    `<span class="pill on" style="font-size:9px">EXECUTED</span><br/><span class="small">${opt.position_qty} @ $${opt.avg_cost.toFixed(2)}</span><br/><span class="small">${opt.executed_at ? opt.executed_at.substring(0,19).replace('T',' ') : ''}</span>` : 
                    `<span class="pill off" style="font-size:9px">MONITORED</span>`
                }
            </td>
        </tr>
        <tr class="option-reasoning-row" id="reasoning-${opt.option_id}" style="display:none">
            <td colspan="9" class="reasoning-cell">
                <strong>Selection Reasoning:</strong>
                <p>${opt.reasoning}</p>
            </td>
        </tr>
    `;
}

/**
 * Show option details when clicked
 */
async function showOptionDetails(optionId) {
    const option = optionsData.options.find(o => o.option_id === optionId);
    if (!option) return;
    
    // Toggle reasoning visibility
    const reasoningRow = document.getElementById(`reasoning-${optionId}`);
    if (reasoningRow.style.display === 'none') {
        // Hide all other reasoning rows
        document.querySelectorAll('.option-reasoning-row').forEach(row => row.style.display = 'none');
        reasoningRow.style.display = 'table-row';
    } else {
        reasoningRow.style.display = 'none';
    }
    
    // Update detail box in right panel
    const detailBox = document.getElementById('detail_box');
    detailBox.innerHTML = `
        <div class="option-detail">
            <h3>${option.underlying} ${option.strike}${option.type[0]} ${option.expiration}</h3>
            <div class="detail-section">
                <strong>Contract:</strong> ${option.contract}
            </div>
            <div class="detail-section">
                <strong>Type:</strong> ${option.type} 
                <span class="moneyness-badge ${option.moneyness.toLowerCase()}">${option.moneyness}</span>
            </div>
            <div class="detail-section">
                <strong>Spot Price:</strong> $${option.spot_price.toFixed(2)}
            </div>
            <div class="detail-section">
                <strong>Strike:</strong> $${option.strike.toFixed(2)}
            </div>
            <div class="detail-section">
                <strong>Expiration:</strong> ${option.expiration} (${option.dte} days)
            </div>
            <div class="divider"></div>
            <div class="detail-section">
                <strong>Pricing:</strong><br/>
                Last: $${option.last_price.toFixed(2)}<br/>
                Bid: $${option.bid.toFixed(2)}<br/>
                Ask: $${option.ask.toFixed(2)}
            </div>
            <div class="detail-section">
                <strong>Liquidity:</strong><br/>
                Volume: ${option.volume.toLocaleString()}<br/>
                Open Interest: ${option.open_interest.toLocaleString()}
            </div>
            <div class="divider"></div>
            <div class="detail-section">
                <strong>Greeks:</strong><br/>
                Delta: <span class="${option.delta >= 0 ? 'positive' : 'negative'}">${option.delta.toFixed(4)}</span><br/>
                Gamma: ${option.gamma.toFixed(4)}<br/>
                Theta: <span class="${option.theta >= 0 ? 'positive' : 'negative'}">${option.theta.toFixed(4)}</span><br/>
                Vega: ${option.vega.toFixed(4)}
            </div>
            <div class="detail-section">
                <strong>IV:</strong> ${(option.iv * 100).toFixed(2)}%
            </div>
            <div class="divider"></div>
            <div class="detail-section">
                <strong>Selection Reasoning:</strong><br/>
                <p class="small">${option.reasoning}</p>
            </div>
            <div class="detail-section small">
                <strong>Last Updated:</strong><br/>
                ${option.last_updated}
            </div>
        </div>
    `;
}

/**
 * Sort table by column
 */
function sortBy(column) {
    if (sortColumn === column) {
        sortAscending = !sortAscending;
    } else {
        sortColumn = column;
        sortAscending = true;
    }
    renderOptionsTab();
}

/**
 * Apply filters
 */
function applyFilters() {
    filterUnderlying = document.getElementById('filter-underlying').value;
    filterType = document.getElementById('filter-type').value;
    renderOptionsTab();
}

/**
 * Start options auto-refresh
 */
function startOptionsRefresh() {
    if (optionsRefreshTimer) {
        clearInterval(optionsRefreshTimer);
    }
    // Refresh every 60 seconds (options don't change as fast as equities)
    optionsRefreshTimer = setInterval(loadOptionsData, 60000);
}

/**
 * Stop options auto-refresh
 */
function stopOptionsRefresh() {
    if (optionsRefreshTimer) {
        clearInterval(optionsRefreshTimer);
        optionsRefreshTimer = null;
    }
}

/**
 * Options worker controls
 */
async function optionsStart() {
    try {
        const resp = await fetch('/api/options/start', { method: 'POST' });
        if (resp.ok) {
            await loadOptionsData();
        }
    } catch (err) {
        console.error('Failed to start options worker:', err);
    }
}

async function optionsStop() {
    try {
        const resp = await fetch('/api/options/stop', { method: 'POST' });
        if (resp.ok) {
            await loadOptionsData();
        }
    } catch (err) {
        console.error('Failed to stop options worker:', err);
    }
}

async function stepOptions() {
    try {
        const resp = await fetch('/api/options/step', { method: 'POST' });
        if (resp.ok) {
            setTimeout(loadOptionsData, 2000); // Refresh after 2 seconds
        }
    } catch (err) {
        console.error('Failed to step options worker:', err);
    }
}

// Initialize when tab is shown
document.addEventListener('DOMContentLoaded', () => {
    // Load options data when options tab is clicked
    const optionsTabButton = document.querySelector('[data-tab="options"]');
    if (optionsTabButton) {
        optionsTabButton.addEventListener('click', () => {
            if (!optionsData) {
                loadOptionsData();
            }
            startOptionsRefresh();
        });
    }
});
