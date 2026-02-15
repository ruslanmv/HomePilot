/**
 * HomePilot Community Gallery — Client-side logic
 *
 * Fetches registry.json and renders persona cards with search, tag
 * filtering, content rating, and sorting.
 *
 * Supports three source modes:
 *   1. Default (GitHub Pages) — reads ./registry.json from the same origin
 *   2. Worker mode — reads from a Cloudflare Worker URL
 *   3. R2 direct mode — reads from an R2 public bucket URL
 *
 * Configure by setting window.GALLERY_API and window.GALLERY_MODE in the
 * HTML before this script loads.
 *
 * Zero dependencies. Vanilla JS. Works offline once cached.
 */
(function () {
  "use strict";

  // ── Configuration ──────────────────────────────────────────────
  var GALLERY_API  = (window.GALLERY_API || "").replace(/\/+$/, "");
  var GALLERY_MODE = window.GALLERY_MODE || "";  // "worker", "r2", or "" (GitHub Pages)

  /**
   * Build the registry fetch URL.
   * - GitHub Pages: ./registry.json (relative to page)
   * - Worker:       <api>/registry.json
   * - R2:           <api>/registry/registry.json
   */
  function registryUrl() {
    if (!GALLERY_API) return "./registry.json";
    if (GALLERY_MODE === "r2") return GALLERY_API + "/registry/registry.json";
    return GALLERY_API + "/registry.json";
  }

  /**
   * Resolve a relative URL from the registry to absolute.
   * When using a remote API, prepends the base URL.
   * When using GitHub Pages, returns as-is (relative to docs/).
   */
  function resolveUrl(url) {
    if (!url) return "";
    if (url.startsWith("http")) return url;
    if (!GALLERY_API) return url;  // GitHub Pages — keep relative
    if (url.startsWith("/")) return GALLERY_API + url;
    return GALLERY_API + "/" + url;
  }

  // Cache bust: append timestamp query to avoid stale CDN caches
  var CACHE_TTL = 5 * 60 * 1000; // 5 minutes

  // ── DOM refs ───────────────────────────────────────────────────
  var $grid        = document.getElementById("grid");
  var $status      = document.getElementById("status");
  var $statsBar    = document.getElementById("stats-bar");
  var $showCount   = document.getElementById("showing-count");
  var $totalCount  = document.getElementById("total-count");
  var $search      = document.getElementById("search");
  var $filterTag   = document.getElementById("filter-tag");
  var $filterRate  = document.getElementById("filter-rating");
  var $sort        = document.getElementById("sort");

  // ── State ──────────────────────────────────────────────────────
  var allItems = [];
  var allTags  = [];

  // ── Helpers ────────────────────────────────────────────────────

  function formatSize(bytes) {
    if (!bytes) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  function escapeHtml(str) {
    var d = document.createElement("div");
    d.textContent = str || "";
    return d.innerHTML;
  }

  function showLoading() {
    $status.innerHTML = '<div class="loading"><div class="spinner"></div>Loading community personas...</div>';
  }

  function showError(msg) {
    $status.innerHTML = '<div class="error-banner">' + escapeHtml(msg) + '</div>';
  }

  function showEmpty(query) {
    var msg = query
      ? 'No personas match "' + escapeHtml(query) + '"'
      : "No personas in the gallery yet";
    $grid.innerHTML = [
      '<div class="empty">',
      '  <div class="empty-icon">🎭</div>',
      '  <div class="empty-title">' + msg + '</div>',
      '  <div class="empty-text">',
      query
        ? "Try a different search term or clear the filters."
        : 'Be the first to share! <a href="https://github.com/ruslanmv/HomePilot/issues/new?template=persona-submission.yml" target="_blank" rel="noopener">Submit a Persona</a>',
      '  </div>',
      '</div>',
    ].join("\n");
  }

  // ── Fetch registry ─────────────────────────────────────────────

  async function fetchRegistryFrom(url) {
    var resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return resp.json();
  }

  async function fetchRegistry() {
    showLoading();

    try {
      var data;
      var primaryUrl = registryUrl();

      try {
        data = await fetchRegistryFrom(primaryUrl);
      } catch (primaryErr) {
        // Fallback to GitHub Pages local registry.json
        if (GALLERY_API) {
          console.warn("Primary registry failed (" + primaryErr.message + "), falling back to local registry.json");
          data = await fetchRegistryFrom("./registry.json?_=" + Date.now());
        } else {
          throw primaryErr;
        }
      }

      allItems = data.items || [];

      // Collect all unique tags
      var tagSet = new Set();
      allItems.forEach(function (item) {
        (item.tags || []).forEach(function (t) { tagSet.add(t); });
      });
      allTags = Array.from(tagSet).sort();

      populateTagFilter();
      $status.innerHTML = "";
      render();
    } catch (err) {
      showError("Failed to load persona registry: " + err.message);
      console.error("Gallery fetch error:", err);
    }
  }

  // ── Populate tag dropdown ──────────────────────────────────────

  function populateTagFilter() {
    // Preserve current selection
    var current = $filterTag.value;
    $filterTag.innerHTML = '<option value="">All Tags</option>';

    allTags.forEach(function (tag) {
      var opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = tag.charAt(0).toUpperCase() + tag.slice(1);
      $filterTag.appendChild(opt);
    });

    if (current && allTags.includes(current)) {
      $filterTag.value = current;
    }
  }

  // ── Filter + Sort ──────────────────────────────────────────────

  function getFiltered() {
    var query   = ($search.value || "").toLowerCase().trim();
    var tag     = $filterTag.value;
    var rating  = $filterRate.value;
    var sortBy  = $sort.value;

    var items = allItems.filter(function (item) {
      // Rating filter
      if (rating === "sfw" && item.nsfw) return false;
      if (rating === "nsfw" && !item.nsfw) return false;

      // Tag filter
      if (tag && !(item.tags || []).includes(tag)) return false;

      // Search
      if (query) {
        var hay = [item.name, item.short, item.author, (item.tags || []).join(" ")].join(" ").toLowerCase();
        if (hay.indexOf(query) === -1) return false;
      }

      return true;
    });

    // Sort
    items.sort(function (a, b) {
      if (sortBy === "newest") {
        return (b.submitted_at || "").localeCompare(a.submitted_at || "");
      }
      if (sortBy === "size") {
        return ((a.latest || {}).size_bytes || 0) - ((b.latest || {}).size_bytes || 0);
      }
      // Default: name A-Z
      return (a.name || "").localeCompare(b.name || "");
    });

    return items;
  }

  // ── Render cards ───────────────────────────────────────────────

  function renderCard(item) {
    var latest = item.latest || {};
    var previewUrl = resolveUrl(latest.preview_url);
    var packageUrl = resolveUrl(latest.package_url);
    var tags = item.tags || [];
    var nsfw = item.nsfw;
    var sizeStr = formatSize(latest.size_bytes);
    var version = latest.version || "1.0.0";

    // Preview image — onerror degrades to placeholder silently
    var previewHtml;
    if (previewUrl) {
      previewHtml = '<img src="' + escapeHtml(previewUrl) + '" alt="' + escapeHtml(item.name) + ' preview" loading="lazy" onerror="this.outerHTML=\'<div class=placeholder>🎭</div>\'" />';
    } else {
      previewHtml = '<div class="placeholder">🎭</div>';
    }

    // Content rating badge
    var ratingBadge = nsfw
      ? '<span class="card-nsfw">NSFW</span>'
      : '<span class="card-rating-sfw">SFW</span>';

    // Tags HTML
    var tagsHtml = tags.map(function (t) {
      return '<span class="tag">' + escapeHtml(t) + '</span>';
    }).join("");

    // GitHub issue link
    var issueLink = item.issue_number
      ? '<a href="https://github.com/ruslanmv/HomePilot/issues/' + item.issue_number + '" target="_blank" rel="noopener">#' + item.issue_number + '</a>'
      : '';

    return [
      '<article class="card">',
      '  <div class="card-preview">',
      '    ' + previewHtml,
      '    ' + ratingBadge,
      '  </div>',
      '  <div class="card-body">',
      '    <div class="card-name" title="' + escapeHtml(item.name) + '">' + escapeHtml(item.name) + '</div>',
      '    <div class="card-short">' + escapeHtml(item.short) + '</div>',
      '    <div class="card-tags">' + tagsHtml + '</div>',
      '    <div class="card-meta">',
      '      <span class="card-author">by @' + escapeHtml(item.author || "community") + ' ' + issueLink + '</span>',
      '      <span class="card-size">v' + escapeHtml(version) + (sizeStr ? " &middot; " + sizeStr : "") + '</span>',
      '    </div>',
      '    <div class="card-actions">',
      packageUrl
        ? '      <a href="' + escapeHtml(packageUrl) + '" class="card-btn card-btn--download" download>' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
          'Download</a>'
        : '',
      latest.card_url
        ? '      <a href="' + escapeHtml(resolveUrl(latest.card_url)) + '" class="card-btn card-btn--details" target="_blank" rel="noopener">Details</a>'
        : '',
      '    </div>',
      '  </div>',
      '</article>',
    ].join("\n");
  }

  function render() {
    var items = getFiltered();

    $totalCount.textContent = allItems.length;
    $showCount.textContent  = items.length;
    $statsBar.style.display = allItems.length > 0 ? "flex" : "none";

    if (items.length === 0) {
      showEmpty($search.value);
      return;
    }

    $grid.innerHTML = items.map(renderCard).join("\n");
  }

  // ── Event listeners ────────────────────────────────────────────

  var debounceTimer;
  $search.addEventListener("input", function () {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(render, 200);
  });
  $filterTag.addEventListener("change", render);
  $filterRate.addEventListener("change", render);
  $sort.addEventListener("change", render);

  // ── Init ───────────────────────────────────────────────────────
  fetchRegistry();
})();
