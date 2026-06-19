// Global State for UI
let localConfig = {
    links: [],
    num_tabs: 1,
    incognito: true,
    randomize_order: false,
    random_scroll: true,
    random_click: true,
    delay_after_scroll: 2.0,
    auto_close: true,
    close_after_seconds: 5,
    capture_screenshots: true,
    use_selenium: true,
    action_delay: 2.0,
};

let currentTab = "dashboard";
let statusPollInterval = null;
let lastLogCount = 0;

// API Endpoints
const API = {
    getConfig: "/api/config",
    saveConfig: "/api/config",
    getHistory: "/api/history",
    getStatus: "/api/status",
    run: "/api/run",
    stop: "/api/stop",
    getScreenshots: "/api/screenshots"
};

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initSliders();
    initUrlManager();
    initEventListeners();
    
    // Load config and history
    loadConfigFromServer();
    loadHistoryFromServer();
    loadGalleryFromServer();
    
    // Start status polling
    startStatusPolling();
});

// Navigation Controller
function initNavigation() {
    const navItems = document.querySelectorAll(".nav-item");
    const sections = document.querySelectorAll(".tab-content");
    const pageTitle = document.getElementById("pageTitle");

    navItems.forEach(item => {
        item.addEventListener("click", () => {
            const targetTab = item.getAttribute("data-tab");
            
            // Toggle active classes on nav
            navItems.forEach(nav => nav.classList.remove("active"));
            item.classList.add("active");

            // Toggle active classes on sections
            sections.forEach(sec => sec.classList.remove("active"));
            const targetSection = document.getElementById(`tab-${targetTab}`);
            if (targetSection) targetSection.classList.add("active");

            // Update title
            pageTitle.textContent = item.textContent.trim();
            currentTab = targetTab;

            // Trigger specific loads
            if (targetTab === "gallery") {
                loadGalleryFromServer();
            } else if (targetTab === "history") {
                loadHistoryFromServer();
            }
        });
    });
}

// Setup Sliders event listeners
function initSliders() {
    const actionSlider = document.getElementById("action_delay");
    const actionVal = document.getElementById("actionDelayVal");
    actionSlider.addEventListener("input", (e) => {
        actionVal.textContent = e.target.value;
    });

    const scrollSlider = document.getElementById("delay_after_scroll");
    const scrollVal = document.getElementById("scrollDelayVal");
    scrollSlider.addEventListener("input", (e) => {
        scrollVal.textContent = e.target.value;
    });

    // Toggle close_after_seconds field display based on auto_close checkbox
    const autoCloseCheck = document.getElementById("auto_close");
    const closeGroup = document.getElementById("closeAfterGroup");
    autoCloseCheck.addEventListener("change", () => {
        closeGroup.style.display = autoCloseCheck.checked ? "flex" : "none";
    });
}

// URL List Management logic
function initUrlManager() {
    const urlInput = document.getElementById("urlInput");
    const btnAddUrl = document.getElementById("btnAddUrl");
    const btnClearUrls = document.getElementById("btnClearUrls");

    btnAddUrl.addEventListener("click", () => {
        let url = urlInput.value.trim();
        if (!url) return;

        // Basic validation helper
        try {
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                url = "https://" + url;
            }
            new URL(url); // will throw error if invalid
            
            localConfig.links.push(url);
            urlInput.value = "";
            renderUrlList();
            showToast("URL added to list", "info");
        } catch (e) {
            showToast("Please enter a valid URL", "error");
        }
    });

    urlInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            btnAddUrl.click();
        }
    });

    btnClearUrls.addEventListener("click", () => {
        if (localConfig.links.length === 0) return;
        if (confirm("Are you sure you want to clear the target URL list?")) {
            localConfig.links = [];
            renderUrlList();
            showToast("URL list cleared", "info");
        }
    });
}

function renderUrlList() {
    const listContainer = document.getElementById("urlList");
    const countSpan = document.getElementById("urlCount");
    
    listContainer.innerHTML = "";
    countSpan.textContent = localConfig.links.length;

    if (localConfig.links.length === 0) {
        listContainer.innerHTML = `<li class="url-item" style="color:var(--text-muted); font-style:italic; justify-content:center;">No URLs configured yet.</li>`;
        return;
    }

    localConfig.links.forEach((link, index) => {
        const li = document.createElement("li");
        li.className = "url-item";

        const text = document.createElement("span");
        text.className = "url-text";
        text.title = link;
        text.textContent = link;

        const removeBtn = document.createElement("button");
        removeBtn.className = "btn-remove-url";
        removeBtn.innerHTML = `
            <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2.5" fill="none" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"></polyline>
                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
        `;
        removeBtn.addEventListener("click", () => {
            localConfig.links.splice(index, 1);
            renderUrlList();
        });

        li.appendChild(text);
        li.appendChild(removeBtn);
        listContainer.appendChild(li);
    });
}

// Event Listeners setup
function initEventListeners() {
    // Run Session Trigger / Stop Action
    const btnRunAction = document.getElementById("btnRunAction");
    btnRunAction.addEventListener("click", () => {
        const isRunning = btnRunAction.classList.contains("btn-danger");
        if (isRunning) {
            triggerStopSession();
        } else {
            triggerRunSession();
        }
    });

    // Save Configuration
    document.getElementById("btnSaveConfig").addEventListener("click", () => {
        saveConfigToServer();
    });

    // Clear Terminal Logs
    document.getElementById("btnClearLogs").addEventListener("click", () => {
        const terminalBody = document.getElementById("terminalLog");
        terminalBody.innerHTML = `<div class="log-line system-msg">[Console cleared]</div>`;
        lastLogCount = 0;
    });

    // Refresh Gallery
    document.getElementById("btnRefreshGallery").addEventListener("click", () => {
        loadGalleryFromServer();
    });

    // Refresh History
    document.getElementById("btnRefreshHistory").addEventListener("click", () => {
        loadHistoryFromServer();
    });

    // Lightbox Controls
    const lightbox = document.getElementById("lightbox");
    const closeLightbox = document.getElementById("btnExitLightbox");
    const lightboxOverlay = document.getElementById("lightboxOverlay");

    const hideLightbox = () => lightbox.classList.remove("active");
    closeLightbox.addEventListener("click", hideLightbox);
    lightboxOverlay.addEventListener("click", hideLightbox);
}

// Config Server Operations
async function loadConfigFromServer() {
    try {
        const response = await fetch(API.getConfig);
        if (!response.ok) throw new Error("Failed to load configuration");
        
        const data = await response.json();
        localConfig = data;
        
        // Populates elements
        document.getElementById("num_tabs").value = localConfig.num_tabs;
        document.getElementById("incognito").checked = localConfig.incognito;
        document.getElementById("random_scroll").checked = localConfig.random_scroll;
        document.getElementById("random_click").checked = localConfig.random_click;
        document.getElementById("capture_screenshots").checked = localConfig.capture_screenshots;
        document.getElementById("randomize_order").checked = localConfig.randomize_order;
        
        document.getElementById("auto_close").checked = localConfig.auto_close;
        document.getElementById("close_after_seconds").value = localConfig.close_after_seconds;
        document.getElementById("closeAfterGroup").style.display = localConfig.auto_close ? "flex" : "none";

        document.getElementById("action_delay").value = localConfig.action_delay;
        document.getElementById("actionDelayVal").textContent = localConfig.action_delay;

        document.getElementById("delay_after_scroll").value = localConfig.delay_after_scroll;
        document.getElementById("scrollDelayVal").textContent = localConfig.delay_after_scroll;

        renderUrlList();
    } catch (e) {
        showToast(e.message, "error");
    }
}

async function saveConfigToServer() {
    // Pack data from UI
    localConfig.num_tabs = parseInt(document.getElementById("num_tabs").value) || 1;
    localConfig.incognito = document.getElementById("incognito").checked;
    localConfig.random_scroll = document.getElementById("random_scroll").checked;
    localConfig.random_click = document.getElementById("random_click").checked;
    localConfig.capture_screenshots = document.getElementById("capture_screenshots").checked;
    localConfig.randomize_order = document.getElementById("randomize_order").checked;
    localConfig.auto_close = document.getElementById("auto_close").checked;
    localConfig.close_after_seconds = parseInt(document.getElementById("close_after_seconds").value) || 5;
    localConfig.action_delay = parseFloat(document.getElementById("action_delay").value);
    localConfig.delay_after_scroll = parseFloat(document.getElementById("delay_after_scroll").value);

    try {
        const response = await fetch(API.saveConfig, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(localConfig)
        });

        if (!response.ok) throw new Error("Failed to save configuration settings");
        
        showToast("Configuration saved successfully", "success");
    } catch (e) {
        showToast(e.message, "error");
    }
}

// History Server Operations
async function loadHistoryFromServer() {
    try {
        const response = await fetch(API.getHistory);
        if (!response.ok) throw new Error("Failed to fetch execution history");
        
        const historyData = await response.json();
        renderHistoryTable(historyData);
        updateDashboardMetrics(historyData);
    } catch (e) {
        console.error(e);
    }
}

function renderHistoryTable(data) {
    const tableBody = document.getElementById("historyTableBody");
    tableBody.innerHTML = "";

    if (data.length === 0) {
        tableBody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:var(--text-muted); font-style:italic;">No historical run records found.</td></tr>`;
        return;
    }

    data.forEach(row => {
        const tr = document.createElement("tr");

        // Format duration
        const dur = row.duration ? `${row.duration}s` : "-";

        tr.innerHTML = `
            <td>${row.timestamp}</td>
            <td><span class="session-id-val">${row.session_id || "-"}</span></td>
            <td>${row.total_links}</td>
            <td>
                <span class="badge-success">${row.successful_tabs}</span> / 
                <span class="badge-fail">${row.failed_tabs}</span>
            </td>
            <td>${row.scrolls_performed}</td>
            <td>${row.clicks_performed}</td>
            <td>${row.screenshots_count}</td>
            <td>${dur}</td>
        `;
        tableBody.appendChild(tr);
    });
}

function updateDashboardMetrics(historyData) {
    if (historyData.length === 0) {
        document.getElementById("metricSuccessRate").textContent = "-";
        document.getElementById("metricTotalTabs").textContent = "0";
        document.getElementById("metricTotalScrolls").textContent = "0";
        document.getElementById("metricTotalClicks").textContent = "0";
        return;
    }

    // Cumulative stats
    let totalTabs = 0;
    let successfulTabs = 0;
    let totalScrolls = 0;
    let totalClicks = 0;

    historyData.forEach(row => {
        totalTabs += row.total_tabs || 0;
        successfulTabs += row.successful_tabs || 0;
        totalScrolls += row.scrolls_performed || 0;
        totalClicks += row.clicks_performed || 0;
    });

    const rate = totalTabs > 0 ? Math.round((successfulTabs / totalTabs) * 100) : 0;
    
    document.getElementById("metricSuccessRate").textContent = `${rate}%`;
    document.getElementById("metricTotalTabs").textContent = totalTabs;
    document.getElementById("metricTotalScrolls").textContent = totalScrolls;
    document.getElementById("metricTotalClicks").textContent = totalClicks;
}

// Gallery Server Operations
async function loadGalleryFromServer() {
    const container = document.getElementById("galleryContainer");
    
    try {
        const response = await fetch(API.getScreenshots);
        if (!response.ok) throw new Error("Failed to load screenshots database");
        
        const data = await response.json();
        container.innerHTML = "";

        if (data.length === 0) {
            container.innerHTML = `
                <div class="no-data-gallery">
                    <svg viewBox="0 0 24 24" width="48" height="48" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg>
                    <p>No screenshots captured yet. Ensure "Capture Screenshots" is enabled in settings and run a session.</p>
                </div>
            `;
            return;
        }

        data.forEach(session => {
            const block = document.createElement("div");
            block.className = "session-block";

            // Title bar
            const titleBar = document.createElement("div");
            titleBar.className = "session-title-bar";

            const h3 = document.createElement("h3");
            // Format session_id to readable string
            h3.textContent = formatSessionId(session.session_id);

            const badge = document.createElement("span");
            badge.className = "session-badge";
            badge.textContent = session.session_id;

            titleBar.appendChild(h3);
            titleBar.appendChild(badge);
            block.appendChild(titleBar);

            // Grid
            const grid = document.createElement("div");
            grid.className = "screenshots-grid";

            session.screenshots.forEach(src => {
                const card = document.createElement("div");
                card.className = "screenshot-card";

                const img = document.createElement("img");
                img.loading = "lazy";
                img.src = src;

                const cardInfo = document.createElement("div");
                cardInfo.className = "screenshot-card-info";
                
                // Get filename
                const fname = src.split("/").pop();
                const label = document.createElement("span");
                label.className = "label";
                label.textContent = fname;

                const sub = document.createElement("span");
                sub.className = "sub";
                sub.textContent = "Click to inspect details";

                cardInfo.appendChild(label);
                cardInfo.appendChild(sub);
                card.appendChild(img);
                card.appendChild(cardInfo);

                // Open Lightbox on click
                card.addEventListener("click", () => {
                    const lightbox = document.getElementById("lightbox");
                    const lbImg = document.getElementById("lightboxImg");
                    const lbCaption = document.getElementById("lightboxCaption");

                    lbImg.src = src;
                    lbCaption.textContent = `${formatSessionId(session.session_id)} — ${fname}`;
                    lightbox.classList.add("active");
                });

                grid.appendChild(card);
            });

            block.appendChild(grid);
            container.appendChild(block);
        });
    } catch (e) {
        console.error(e);
    }
}

function formatSessionId(idStr) {
    // idStr format: YYYYMMDD_HHMMSS
    if (idStr.length === 15 && idStr[8] === "_") {
        const y = idStr.substring(0, 4);
        const m = idStr.substring(4, 6);
        const d = idStr.substring(6, 8);
        const h = idStr.substring(9, 11);
        const min = idStr.substring(11, 13);
        const s = idStr.substring(13, 15);
        return `Run on ${y}-${m}-${d} at ${h}:${min}:${s}`;
    }
    return idStr;
}

// Session Execution Controls
async function triggerRunSession() {
    if (localConfig.links.length === 0) {
        showToast("Cannot run session: URL target list is empty.", "error");
        return;
    }

    try {
        const response = await fetch(API.run, { method: "POST" });
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || "Failed to trigger session");
        }
        
        lastLogCount = 0;
        showToast("Automation session started", "success");
    } catch (e) {
        showToast(e.message, "error");
    }
}

async function triggerStopSession() {
    try {
        const response = await fetch(API.stop, { method: "POST" });
        if (!response.ok) throw new Error("Failed to stop session");
        
        showToast("Cancellation request submitted", "info");
    } catch (e) {
        showToast(e.message, "error");
    }
}

// Execution Status Monitoring (Polling)
function startStatusPolling() {
    if (statusPollInterval) clearInterval(statusPollInterval);
    
    // Fetch immediately, then loop
    fetchStatus();
    statusPollInterval = setInterval(fetchStatus, 1500);
}

async function fetchStatus() {
    try {
        const response = await fetch(API.getStatus);
        if (!response.ok) throw new Error("Failed to get runner status");
        
        const state = await response.json();
        updateUIState(state);
    } catch (e) {
        console.error("Status check failed: ", e);
    }
}

function updateUIState(state) {
    const statusDot = document.getElementById("statusDot");
    const statusText = document.getElementById("statusText");
    const activeSessionInfo = document.getElementById("activeSessionInfo");
    const currentSessionId = document.getElementById("currentSessionId");
    
    const btnRunAction = document.getElementById("btnRunAction");
    const progressBarContainer = document.getElementById("globalProgressBarContainer");
    const progressFill = document.getElementById("progressFill");
    const progressPctText = document.getElementById("progressPctText");

    const currentUrlVal = document.getElementById("currentUrlVal");

    // Handle running vs idle displays
    if (state.status === "running") {
        // Dot & Badge
        statusDot.className = "status-dot pulse-running";
        statusText.textContent = "Running Automation";
        
        activeSessionInfo.style.display = "flex";
        currentSessionId.textContent = state.session_id;

        // Button state
        btnRunAction.className = "btn btn-danger btn-run";
        btnRunAction.querySelector("span").textContent = "Stop Session";
        btnRunAction.querySelector("svg").innerHTML = `<rect x="4" y="4" width="16" height="16" fill="currentColor"></rect>`;

        // Progress bar calculation
        if (state.total_tabs > 0) {
            progressBarContainer.style.opacity = "1";
            const pct = Math.round((state.completed_tabs / state.total_tabs) * 100);
            progressFill.style.width = `${pct}%`;
            progressPctText.textContent = `${state.completed_tabs} / ${state.total_tabs} tabs (${pct}%)`;
        }

        // Current task
        currentUrlVal.textContent = state.current_url || "Opening browser...";
    } else {
        // Dot & Badge
        statusDot.className = "status-dot pulse-idle";
        statusText.textContent = "System Idle";
        
        activeSessionInfo.style.display = "none";

        // Button state
        btnRunAction.className = "btn btn-primary btn-run";
        btnRunAction.querySelector("span").textContent = "Run Session";
        btnRunAction.querySelector("svg").innerHTML = `<polygon points="5 3 19 12 5 21 5 3" fill="currentColor"></polygon>`;

        progressBarContainer.style.opacity = "0";
        currentUrlVal.textContent = "None";

        // If it transitioned from running to idle, refresh details
        if (btnRunAction.dataset.prevStatus === "running") {
            loadHistoryFromServer();
            loadGalleryFromServer();
            showToast("Automation execution completed", "info");
        }
    }

    btnRunAction.dataset.prevStatus = state.status;

    // Render Logs dynamically
    renderLogs(state.logs);
}

function renderLogs(logs) {
    const terminalBody = document.getElementById("terminalLog");
    if (!logs || logs.length === 0) return;

    // Only append if logs count increased or it is a new run
    if (logs.length > lastLogCount) {
        // If console is clear but server sent more logs, clear system welcome message first
        if (lastLogCount === 0) {
            terminalBody.innerHTML = "";
        }

        const newLogs = logs.slice(lastLogCount);
        newLogs.forEach(line => {
            const div = document.createElement("div");
            
            // Assign class based on keywords
            if (line.includes(" OK |") || line.includes("successful")) {
                div.className = "log-line ok-msg";
            } else if (line.includes(" FAILED |") || line.includes("ERROR:") || line.includes("fail")) {
                div.className = "log-line fail-msg";
            } else if (line.includes("Processing Tab") || line.includes("Starting:")) {
                div.className = "log-line info-msg";
            } else if (line.includes("Cancel request") || line.includes("Stop requested")) {
                div.className = "log-line warn-msg";
            } else if (line.includes("System") || line.includes("Ready")) {
                div.className = "log-line system-msg";
            } else {
                div.className = "log-line";
            }

            div.textContent = line;
            terminalBody.appendChild(div);
        });

        lastLogCount = logs.length;
        
        // Auto scroll container
        terminalBody.scrollTop = terminalBody.scrollHeight;
    }
}

// Toast Notification System
function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;

    let icon = "";
    if (type === "success") {
        icon = `<svg viewBox="0 0 24 24" width="20" height="20" stroke="var(--accent-emerald)" stroke-width="2.5" fill="none"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
    } else if (type === "error") {
        icon = `<svg viewBox="0 0 24 24" width="20" height="20" stroke="var(--accent-rose)" stroke-width="2.5" fill="none"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>`;
    } else {
        icon = `<svg viewBox="0 0 24 24" width="20" height="20" stroke="var(--accent-cyan)" stroke-width="2.5" fill="none"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg>`;
    }

    toast.innerHTML = `
        <div class="toast-icon">${icon}</div>
        <div class="toast-msg">${message}</div>
    `;

    container.appendChild(toast);

    // Fade out and remove
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => {
            toast.remove();
        }, 300);
    }, 3500);
}
