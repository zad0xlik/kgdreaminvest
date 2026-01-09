/* Transactions tab - Portfolio performance chart and trade history */

let transactionsChart = null;
let transactionsData = null;

async function loadTransactions() {
  try {
    transactionsData = await fetchJSON("/api/transactions");
    renderTransactionsChart();
    renderTransactionsTable();
    renderTransactionsSummary();
  } catch (e) {
    console.error("Error loading transactions:", e);
    document.getElementById("transactions-content").innerHTML = 
      '<div style="text-align:center;padding:40px;color:#ef4444">Error loading transactions data</div>';
  }
}

function renderTransactionsChart() {
  const ctx = document.getElementById('transactions-chart').getContext('2d');
  
  if (transactionsChart) {
    transactionsChart.destroy();
  }
  
  if (!transactionsData || !transactionsData.timeline || transactionsData.timeline.length === 0) {
    return;
  }
  
  // Prepare chart data
  const timeline = transactionsData.timeline;
  const labels = timeline.map(t => t.timestamp ? new Date(t.timestamp) : null).filter(d => d !== null);
  const portfolioValues = timeline.map(t => t.portfolio_value);
  
  // Separate buy and sell trade markers
  const buyTrades = [];
  const sellTrades = [];
  
  timeline.forEach((point, index) => {
    if (point.trade) {
      const tradePoint = {
        x: point.timestamp ? new Date(point.timestamp) : null,
        y: point.portfolio_value,
        symbol: point.trade.symbol,
        side: point.trade.side,
        qty: point.trade.qty,
        price: point.trade.price,
        notional: point.trade.notional
      };
      
      if (point.trade.side === 'BUY') {
        buyTrades.push(tradePoint);
      } else {
        sellTrades.push(tradePoint);
      }
    }
  });
  
  // Create chart
  transactionsChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Portfolio Value',
          data: portfolioValues,
          borderColor: '#a78bfa',
          backgroundColor: 'rgba(167, 139, 250, 0.1)',
          borderWidth: 2,
          fill: true,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 6,
          pointHoverBackgroundColor: '#a78bfa',
          pointHoverBorderColor: '#fff',
          pointHoverBorderWidth: 2
        },
        {
          label: 'BUY',
          data: buyTrades,
          type: 'scatter',
          backgroundColor: '#10b981',
          borderColor: '#fff',
          borderWidth: 2,
          pointRadius: 8,
          pointHoverRadius: 12,
          pointStyle: 'circle'
        },
        {
          label: 'SELL',
          data: sellTrades,
          type: 'scatter',
          backgroundColor: '#ef4444',
          borderColor: '#fff',
          borderWidth: 2,
          pointRadius: 8,
          pointHoverRadius: 12,
          pointStyle: 'circle'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'nearest',
        axis: 'x',
        intersect: false
      },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: {
            color: '#e5e7eb',
            font: { size: 12 },
            usePointStyle: true,
            padding: 15
          }
        },
        tooltip: {
          backgroundColor: 'rgba(17, 24, 39, 0.95)',
          titleColor: '#e5e7eb',
          bodyColor: '#e5e7eb',
          borderColor: '#374151',
          borderWidth: 1,
          padding: 12,
          displayColors: true,
          callbacks: {
            title: function(context) {
              if (context[0].raw.x) {
                return convertToUserTimezone(context[0].raw.x.toISOString());
              }
              return convertToUserTimezone(new Date(labels[context[0].dataIndex]).toISOString());
            },
            label: function(context) {
              const dataset = context.dataset;
              
              if (dataset.label === 'Portfolio Value') {
                return `Portfolio: $${context.parsed.y.toFixed(2)}`;
              } else {
                const trade = context.raw;
                return [
                  `${trade.side} ${trade.symbol}`,
                  `Qty: ${trade.qty.toFixed(4)}`,
                  `Price: $${trade.price.toFixed(2)}`,
                  `Amount: $${trade.notional.toFixed(2)}`
                ];
              }
            }
          }
        }
      },
      scales: {
        x: {
          type: 'time',
          time: {
            unit: 'day',
            displayFormats: {
              day: 'MMM d',
              hour: 'MMM d HH:mm'
            },
            tooltipFormat: 'PPpp'
          },
          grid: {
            color: 'rgba(255, 255, 255, 0.05)'
          },
          ticks: {
            color: '#9ca3af',
            font: { size: 11 }
          }
        },
        y: {
          beginAtZero: false,
          grid: {
            color: 'rgba(255, 255, 255, 0.05)'
          },
          ticks: {
            color: '#9ca3af',
            font: { size: 11 },
            callback: function(value) {
              return '$' + value.toFixed(0);
            }
          },
          title: {
            display: true,
            text: 'Portfolio Value ($)',
            color: '#e5e7eb',
            font: { size: 12, weight: 'bold' }
          }
        }
      }
    }
  });
}

function renderTransactionsTable() {
  if (!transactionsData || !transactionsData.trades) {
    return;
  }
  
  const trades = transactionsData.trades;
  const tbody = document.getElementById('transactions-table-body');
  
  tbody.innerHTML = trades.map(trade => {
    const sideClass = trade.side === 'BUY' ? 'trade-buy' : 'trade-sell';
    const amountPrefix = trade.side === 'BUY' ? '-' : '+';
    const timestamp = convertToUserTimezone(trade.ts);
    
    return `<tr class="${sideClass}">
      <td>${trade.trade_id}</td>
      <td class="small">${timestamp}</td>
      <td><b>${trade.symbol}</b></td>
      <td><span class="pill ${trade.side === 'BUY' ? 'buy-badge' : 'sell-badge'}">${trade.side}</span></td>
      <td>${trade.qty.toFixed(4)}</td>
      <td>$${trade.price.toFixed(2)}</td>
      <td>${amountPrefix}$${trade.notional.toFixed(2)}</td>
      <td>$${trade.cash_after.toFixed(2)}</td>
    </tr>`;
  }).join('');
}

function renderTransactionsSummary() {
  if (!transactionsData || !transactionsData.summary) {
    return;
  }
  
  const s = transactionsData.summary;
  
  document.getElementById('summary-start').textContent = `$${s.start_balance.toFixed(2)}`;
  document.getElementById('summary-current').textContent = `$${s.current_total.toFixed(2)}`;
  document.getElementById('summary-gain').textContent = `$${s.total_gain.toFixed(2)}`;
  document.getElementById('summary-return').textContent = `${s.total_return_pct >= 0 ? '+' : ''}${s.total_return_pct.toFixed(2)}%`;
  document.getElementById('summary-trades').textContent = s.trade_count;
  document.getElementById('summary-invested').textContent = `$${s.total_invested.toFixed(2)}`;
  document.getElementById('summary-sold').textContent = `$${s.total_sold.toFixed(2)}`;
  document.getElementById('summary-realized').textContent = `$${s.realized_gain.toFixed(2)}`;
  document.getElementById('summary-unrealized').textContent = `$${s.unrealized_gain.toFixed(2)}`;
  document.getElementById('summary-cash').textContent = `$${s.current_cash.toFixed(2)}`;
  document.getElementById('summary-equity').textContent = `$${s.current_equity.toFixed(2)}`;
  
  // Color code gain/loss
  const gainElement = document.getElementById('summary-gain');
  gainElement.className = s.total_gain >= 0 ? 'positive' : 'negative';
  
  const returnElement = document.getElementById('summary-return');
  returnElement.className = s.total_return_pct >= 0 ? 'positive' : 'negative';
  
  const realizedElement = document.getElementById('summary-realized');
  realizedElement.className = s.realized_gain >= 0 ? 'positive' : 'negative';
  
  const unrealizedElement = document.getElementById('summary-unrealized');
  unrealizedElement.className = s.unrealized_gain >= 0 ? 'positive' : 'negative';
}

// Export for use in app.js
window.loadTransactions = loadTransactions;
