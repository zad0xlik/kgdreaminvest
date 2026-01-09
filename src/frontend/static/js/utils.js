/* Utility functions */

async function fetchJSON(url, opts) {
  const r = await fetch(url, opts || {});
  return await r.json();
}

// ============== TIMEZONE UTILITIES ==============

const TIMEZONES = {
  'America/New_York': 'Eastern Time (ET)',
  'America/Chicago': 'Central Time (CT)',
  'America/Los_Angeles': 'Pacific Time (PT)',
  'Europe/London': 'London (GMT/BST)',
  'Asia/Tokyo': 'Tokyo (JST)',
  'Asia/Hong_Kong': 'Hong Kong (HKT)',
  'Australia/Sydney': 'Sydney (AEST)',
  'Europe/Berlin': 'Frankfurt (CET)',
  'Asia/Singapore': 'Singapore (SGT)',
  'Asia/Shanghai': 'Shanghai (CST)'
};

/**
 * Get the user's selected timezone from localStorage
 * Defaults to America/Los_Angeles if not set
 */
function getUserTimezone() {
  return localStorage.getItem('selectedTimezone') || 'America/Los_Angeles';
}

/**
 * Set the user's timezone preference
 */
function setUserTimezone(timezone) {
  localStorage.setItem('selectedTimezone', timezone);
}

/**
 * Convert UTC timestamp to selected timezone
 * @param {string} utcTimestamp - UTC timestamp string (e.g., "2025-12-30T22:23:15")
 * @param {boolean} includeSeconds - Whether to include seconds in output
 * @returns {string} Formatted timestamp in user's timezone
 */
function convertToUserTimezone(utcTimestamp, includeSeconds = true) {
  if (!utcTimestamp) return '—';
  
  const timezone = getUserTimezone();
  const date = new Date(utcTimestamp);
  
  // Check for invalid date
  if (isNaN(date.getTime())) return '—';
  
  const options = {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  };
  
  if (includeSeconds) {
    options.second = '2-digit';
  }
  
  try {
    const formatter = new Intl.DateTimeFormat('en-US', options);
    const parts = formatter.formatToParts(date);
    
    // Extract parts
    const year = parts.find(p => p.type === 'year').value;
    const month = parts.find(p => p.type === 'month').value;
    const day = parts.find(p => p.type === 'day').value;
    const hour = parts.find(p => p.type === 'hour').value;
    const minute = parts.find(p => p.type === 'minute').value;
    
    if (includeSeconds) {
      const second = parts.find(p => p.type === 'second').value;
      return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
    }
    
    return `${year}-${month}-${day} ${hour}:${minute}`;
  } catch (e) {
    console.error('Timezone conversion error:', e);
    return utcTimestamp.substring(0, 19).replace('T', ' ');
  }
}

/**
 * Get timezone abbreviation for display
 */
function getTimezoneAbbr() {
  const timezone = getUserTimezone();
  const date = new Date();
  
  try {
    const formatter = new Intl.DateTimeFormat('en-US', {
      timeZone: timezone,
      timeZoneName: 'short'
    });
    
    const parts = formatter.formatToParts(date);
    const tzPart = parts.find(p => p.type === 'timeZoneName');
    return tzPart ? tzPart.value : '';
  } catch (e) {
    return '';
  }
}

/**
 * Change timezone and refresh the entire UI
 */
function changeTimezone(newTimezone) {
  setUserTimezone(newTimezone);
  // Refresh all data to apply new timezone
  refreshAll();
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
