/**
 * HomePilot Community Personas — Gallery App
 *
 * Fetches the registry from a Cloudflare Worker or R2 public bucket,
 * renders persona cards, and supports search, tag, and content rating
 * filtering.
 *
 * Configure via window.GALLERY_API and window.GALLERY_MODE in index.html.
 */

/* global GALLERY_API, GALLERY_MODE */

// ── URL helpers ─────────────────────────────────────────────────────

/**
 * Build the registry URL for the configured mode.
 * Worker: <base>/registry.json
 * R2:     <base>/registry/registry.json
 */
function registryUrl() {
  var base = (window.GALLERY_API || "").replace(/\/+$/, "");
  if ((window.GALLERY_MODE || "worker") === "r2") {
    return base + "/registry/registry.json";
  }
  return base + "/registry.json";
}

/**
 * Resolve a relative URL from the registry to an absolute URL.
 * Handles both Worker-relative (/p/id/ver) and R2-relative (packages/id/ver/...) formats.
 */
function resolveUrl(url) {
  if (!url) return "";
  if (url.startsWith("http")) return url;
  var base = (window.GALLERY_API || "").replace(/\/+$/, "");
  if (url.startsWith("/")) return base + url;
  return base + "/" + url;
}

// ── DOM helpers ─────────────────────────────────────────────────────

function setStatus(msg) {
  document.getElementById("status").textContent = msg || "";
}

function setStats(items, filtered) {
  var el = document.getElementById("stats");
  if (!items.length) { el.textContent = ""; return; }
  var totalDownloads = items.reduce(function (s, i) { return s + (i.downloads || 0); }, 0);
  var shown = filtered !== undefined ? filtered + " shown of " : "";
  el.textContent = shown + items.length + " personas | " + totalDownloads.toLocaleString() + " total downloads";
}

function formatBytes(bytes) {
  if (!bytes || bytes <= 0) return "";
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1048576).toFixed(1) + " MB";
}

function escapeHtml(str) {
  var d = document.createElement("div");
  d.textContent = str || "";
  return d.innerHTML;
}

function populateTags(items) {
  var tagSet = {};
  for (var i = 0; i < items.length; i++) {
    var tags = items[i].tags || [];
    for (var j = 0; j < tags.length; j++) tagSet[tags[j]] = true;
  }
  var select = document.getElementById("filter-tag");
  while (select.options.length > 1) select.remove(1);
  var sorted = Object.keys(tagSet).sort();
  for (var k = 0; k < sorted.length; k++) {
    var opt = document.createElement("option");
    opt.value = sorted[k];
    opt.textContent = sorted[k].charAt(0).toUpperCase() + sorted[k].slice(1);
    select.appendChild(opt);
  }
}

// ── Render ──────────────────────────────────────────────────────────

function render(items) {
  var grid = document.getElementById("grid");
  grid.innerHTML = "";

  if (!items.length) {
    grid.innerHTML = '<div class="empty"><div class="icon">🎭</div><div class="title">No personas found</div><p>Try a different search or check back later.</p></div>';
    return;
  }

  for (var i = 0; i < items.length; i++) {
    var it = items[i];
    var card = document.createElement("div");
    card.className = "card";

    var latest = it.latest || {};
    var previewUrl = resolveUrl(latest.preview_url);
    var packageUrl = resolveUrl(latest.package_url);
    var cardUrl = resolveUrl(latest.card_url);
    var tags = (it.tags || []).slice(0, 3);
    var sizeText = formatBytes(latest.size_bytes);
    var version = latest.version || "1.0.0";

    var tagsHtml = tags.map(function (t) {
      return '<span class="tag">' + escapeHtml(t) + '</span>';
    }).join("");

    var ratingBadge = it.nsfw
      ? '<span class="nsfw-badge">NSFW</span>'
      : '<span class="sfw-badge">SFW</span>';

    card.innerHTML =
      '<div class="preview-wrap">' +
        (previewUrl
          ? '<img class="preview" src="' + escapeHtml(previewUrl) + '" alt="' + escapeHtml(it.name) + '" loading="lazy" onerror="this.outerHTML=\'<div class=\\\'preview placeholder\\\'>🎭</div>\'" />'
          : '<div class="preview placeholder">🎭</div>') +
        ratingBadge +
      '</div>' +
      '<div class="body">' +
        '<div class="name">' + escapeHtml(it.name) + '</div>' +
        '<div class="short">' + escapeHtml(it.short || "") + '</div>' +
        '<div class="meta">' +
          '<div class="tags">' + tagsHtml + '</div>' +
          '<div class="downloads">' + (it.downloads || 0).toLocaleString() + ' downloads</div>' +
        '</div>' +
        (packageUrl
          ? '<a class="btn" href="' + escapeHtml(packageUrl) + '" download>Download .hpersona</a>'
          : '<button class="btn" disabled>Not available</button>') +
        (sizeText ? '<div class="size">v' + escapeHtml(version) + ' &middot; ' + sizeText + '</div>' : '') +
      '</div>';

    grid.appendChild(card);
  }
}

// ── Boot ────────────────────────────────────────────────────────────

(function boot() {
  var q = document.getElementById("q");
  var filterTag = document.getElementById("filter-tag");
  var filterRating = document.getElementById("filter-rating");
  var refreshBtn = document.getElementById("refresh");
  var all = [];

  function reload() {
    setStatus("Loading registry...");
    fetch(registryUrl(), { cache: "no-store" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function (data) {
        all = data.items || [];
        populateTags(all);
        setStatus("");
        apply();
      })
      .catch(function () {
        setStatus("Could not load registry. The gallery may be offline or not yet deployed.");
        all = [];
        render([]);
        setStats([], 0);
      });
  }

  function apply() {
    var search = (q.value || "").trim().toLowerCase();
    var tag = filterTag.value;
    var rating = filterRating ? filterRating.value : "";

    var filtered = all.filter(function (x) {
      if (rating === "sfw" && x.nsfw) return false;
      if (rating === "nsfw" && !x.nsfw) return false;
      if (tag && !(x.tags || []).includes(tag)) return false;
      if (search) {
        var hay = [x.name, x.short, x.id, (x.tags || []).join(" ")].join(" ").toLowerCase();
        if (hay.indexOf(search) === -1) return false;
      }
      return true;
    });

    render(filtered);
    setStats(all, filtered.length);
  }

  q.addEventListener("input", apply);
  filterTag.addEventListener("change", apply);
  if (filterRating) filterRating.addEventListener("change", apply);
  refreshBtn.addEventListener("click", reload);

  reload();
})();
