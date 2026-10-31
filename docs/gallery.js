/**
 * HomePilot Community Gallery — Client-side logic
 *
 * Fetches registry.json and renders persona cards with search, tag
 * filtering, content rating, sorting, and MMORPG character-sheet
 * detail modals.
 *
 * Supports three source modes:
 *   1. Default (GitHub Pages) — reads ./registry.json from the same origin
 *   2. Worker mode — reads from a Cloudflare Worker URL
 *   3. R2 direct mode — reads from an R2 public bucket URL
 *
 * Zero dependencies. Vanilla JS.
 */
(function () {
  "use strict";

  // ── Configuration ──────────────────────────────────────────────
  var GALLERY_API  = (window.GALLERY_API || "").replace(/\/+$/, "");
  var GALLERY_MODE = window.GALLERY_MODE || "";

  function registryUrl() {
    if (!GALLERY_API) return "./registry.json";
    if (GALLERY_MODE === "r2") return GALLERY_API + "/registry/registry.json";
    return GALLERY_API + "/registry.json";
  }

  function resolveUrl(url) {
    if (!url) return "";
    if (url.startsWith("http")) return url;
    if (!GALLERY_API) return url;

    // R2 registries store object keys, but the production Worker deliberately
    // exposes stable /v, /c and /p routes instead of raw R2 object paths.
    // Translate those keys only in Worker mode. Native Worker URLs (/v/...)
    // and direct R2 mode continue to work without changes.
    if (GALLERY_MODE === "worker") {
      var key = url.replace(/^\/+/, "");
      var preview = key.match(/^previews\/([a-z0-9_-]+)\/([a-z0-9._-]+)\/preview\.(?:webp|png|jpe?g)$/i);
      if (preview) return GALLERY_API + "/v/" + preview[1] + "/" + preview[2];
      var card = key.match(/^previews\/([a-z0-9_-]+)\/([a-z0-9._-]+)\/card\.json$/i);
      if (card) return GALLERY_API + "/c/" + card[1] + "/" + card[2];
      var pkg = key.match(/^packages\/([a-z0-9_-]+)\/([a-z0-9._-]+)\/persona\.hpersona$/i);
      if (pkg) return GALLERY_API + "/p/" + pkg[1] + "/" + pkg[2];
    }

    if (url.startsWith("/")) return GALLERY_API + url;
    return GALLERY_API + "/" + url;
  }

  // ── DOM refs ───────────────────────────────────────────────────
  var $grid       = document.getElementById("grid");
  var $status     = document.getElementById("status");
  var $statsBar   = document.getElementById("stats-bar");
  var $showCount  = document.getElementById("showing-count");
  var $totalCount = document.getElementById("total-count");
  var $search     = document.getElementById("search");
  var $filterTag  = document.getElementById("filter-tag");
  var $filterRate = document.getElementById("filter-rating");
  var $sort       = document.getElementById("sort");

  // Modal refs
  var $modalOverlay     = document.getElementById("modal-overlay");
  var $modalClose       = document.getElementById("modal-close");
  var $modalCloseBtn    = document.getElementById("modal-close-btn");
  var $modalAvatar      = document.getElementById("modal-avatar");
  var $modalClassBadge  = document.getElementById("modal-class-badge");
  var $modalName        = document.getElementById("modal-name");
  var $modalRole        = document.getElementById("modal-role");
  var $modalLevel       = document.getElementById("modal-level");
  var $modalContentRate = document.getElementById("modal-content-rating");
  var $modalStats       = document.getElementById("modal-stats");
  var $modalStyleTags   = document.getElementById("modal-style-tags");
  var $modalToolsSection= document.getElementById("modal-tools-section");
  var $modalTools       = document.getElementById("modal-tools");
  var $modalBackstoryS  = document.getElementById("modal-backstory-section");
  var $modalBackstory   = document.getElementById("modal-backstory");
  var $modalAuthor      = document.getElementById("modal-author");
  var $modalDownloads   = document.getElementById("modal-downloads");
  var $modalVersion     = document.getElementById("modal-version");
  var $modalSize        = document.getElementById("modal-size");
  var $modalDownload    = document.getElementById("modal-download");

  // ── State ──────────────────────────────────────────────────────
  var allItems = [];
  var allTags  = [];
  var cardCache = {};
  var PAGE_SIZE = 48;
  var currentFiltered = [];
  var visibleCount = PAGE_SIZE;

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
        if (GALLERY_API) {
          console.warn("Primary registry failed (" + primaryErr.message + "), falling back to local registry.json");
          data = await fetchRegistryFrom("./registry.json?_=" + Date.now());
        } else {
          throw primaryErr;
        }
      }
      allItems = data.items || [];
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
    var current = $filterTag.value;
    $filterTag.innerHTML = '<option value="">All Tags</option>';
    allTags.forEach(function (tag) {
      var opt = document.createElement("option");
      opt.value = tag;
      opt.textContent = tag.charAt(0).toUpperCase() + tag.slice(1);
      $filterTag.appendChild(opt);
    });
    if (current && allTags.includes(current)) $filterTag.value = current;
  }

  // ── Filter + Sort ──────────────────────────────────────────────

  function getFiltered() {
    var query  = ($search.value || "").toLowerCase().trim();
    var tag    = $filterTag.value;
    var rating = $filterRate.value;
    var sortBy = $sort.value;

    var items = allItems.filter(function (item) {
      if (rating === "sfw" && item.nsfw) return false;
      if (rating === "nsfw" && !item.nsfw) return false;
      if (tag && !(item.tags || []).includes(tag)) return false;
      if (query) {
        var hay = [item.name, item.short, item.author, (item.tags || []).join(" ")].join(" ").toLowerCase();
        if (hay.indexOf(query) === -1) return false;
      }
      return true;
    });

    items.sort(function (a, b) {
      if (sortBy === "newest") return (b.submitted_at || "").localeCompare(a.submitted_at || "");
      if (sortBy === "size") return ((a.latest || {}).size_bytes || 0) - ((b.latest || {}).size_bytes || 0);
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

    var previewHtml;
    if (previewUrl) {
      previewHtml = '<img src="' + escapeHtml(previewUrl) + '" alt="' + escapeHtml(item.name) + ' preview" loading="lazy" onerror="this.outerHTML=\'<div class=placeholder>🎭</div>\'" />';
    } else {
      previewHtml = '<div class="placeholder">🎭</div>';
    }

    var ratingBadge = nsfw
      ? '<span class="card-nsfw">NSFW</span>'
      : '<span class="card-rating-sfw">SFW</span>';

    var tagsHtml = tags.map(function (t) {
      return '<span class="tag">' + escapeHtml(t) + '</span>';
    }).join("");

    var issueLink = item.issue_number
      ? '<a href="https://github.com/ruslanmv/HomePilot/issues/' + item.issue_number + '" target="_blank" rel="noopener">#' + item.issue_number + '</a>'
      : '';

    return [
      '<article class="card" data-persona-id="' + escapeHtml(item.id) + '">',
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
        ? '      <a href="' + escapeHtml(packageUrl) + '" class="card-btn card-btn--download" download onclick="event.stopPropagation()">' +
          '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
          'Download</a>'
        : '',
      '      <button class="card-btn card-btn--details" onclick="event.stopPropagation(); window.__openDetails(\'' + escapeHtml(item.id) + '\')">Details</button>',
      '    </div>',
      '  </div>',
      '</article>',
    ].join("\n");
  }

  function render() {
    currentFiltered = getFiltered();
    visibleCount = PAGE_SIZE;
    $totalCount.textContent = allItems.length;
    $showCount.textContent  = currentFiltered.length;
    $statsBar.style.display = allItems.length > 0 ? "flex" : "none";

    if (currentFiltered.length === 0) {
      showEmpty($search.value);
      updateLoadMore();
      return;
    }

    var slice = currentFiltered.slice(0, visibleCount);
    $grid.innerHTML = slice.map(renderCard).join("\n");
    bindCardClicks();
    updateLoadMore();
  }

  function loadMoreItems() {
    var start = visibleCount;
    visibleCount += PAGE_SIZE;
    var slice = currentFiltered.slice(start, visibleCount);
    $grid.insertAdjacentHTML("beforeend", slice.map(renderCard).join("\n"));
    // Bind only the newly added cards
    var cards = $grid.querySelectorAll(".card");
    for (var i = start; i < Math.min(visibleCount, currentFiltered.length); i++) {
      (function (card) {
        card.addEventListener("click", function () {
          var id = card.getAttribute("data-persona-id");
          if (id) openDetailModal(id);
        });
      })(cards[i]);
    }
    updateLoadMore();
  }

  function bindCardClicks() {
    $grid.querySelectorAll(".card").forEach(function (card) {
      card.addEventListener("click", function () {
        var id = card.getAttribute("data-persona-id");
        if (id) openDetailModal(id);
      });
    });
  }

  function updateLoadMore() {
    var $loadMoreWrap = document.getElementById("load-more-wrap");
    if (!$loadMoreWrap) return;
    if (visibleCount < currentFiltered.length) {
      var remaining = currentFiltered.length - visibleCount;
      $loadMoreWrap.style.display = "flex";
      document.getElementById("load-more-btn").textContent =
        "Load more (" + remaining + " remaining)";
    } else {
      $loadMoreWrap.style.display = "none";
    }
  }

  // ── Character Sheet Modal ──────────────────────────────────────

  function closeModal() {
    $modalOverlay.classList.remove("active");
  }

  $modalClose.addEventListener("click", closeModal);
  $modalCloseBtn.addEventListener("click", closeModal);
  $modalOverlay.addEventListener("click", function (e) {
    if (e.target === $modalOverlay) closeModal();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeModal();
  });

  async function openDetailModal(personaId) {
    var item = allItems.find(function (i) { return i.id === personaId; });
    if (!item) return;

    var latest = item.latest || {};
    var previewUrl = resolveUrl(latest.preview_url);
    var packageUrl = resolveUrl(latest.package_url);
    var cardUrl = resolveUrl(latest.card_url);

    // Set basic info from registry
    $modalName.textContent = item.name;
    $modalRole.textContent = item.short;
    $modalAuthor.textContent = "by @" + (item.author || "community");
    $modalDownloads.textContent = (item.downloads || 0).toLocaleString() + " downloads";
    $modalVersion.textContent = "v" + (latest.version || "1.0.0");
    $modalSize.textContent = formatSize(latest.size_bytes);
    $modalContentRate.textContent = item.nsfw ? "NSFW" : "SFW";
    $modalContentRate.style.color = item.nsfw ? "var(--red)" : "var(--green)";

    // Avatar
    if (previewUrl) {
      $modalAvatar.innerHTML = '<img src="' + escapeHtml(previewUrl) + '" alt="' + escapeHtml(item.name) + '" onerror="this.outerHTML=\'<div class=placeholder>🎭</div>\'" />';
    } else {
      $modalAvatar.innerHTML = '<div class="placeholder">🎭</div>';
    }

    // Download link
    if (packageUrl) {
      $modalDownload.href = packageUrl;
      $modalDownload.style.display = "";
    } else {
      $modalDownload.style.display = "none";
    }

    // Default stats
    var defaultStats = { charisma: 50, elegance: 50, confidence: 50, warmth: 50, level: 1 };
    renderModalStats(defaultStats);
    $modalClassBadge.textContent = item.class_id || "persona";
    $modalStyleTags.innerHTML = (item.tags || []).map(function (t) {
      return '<span class="modal-tag">' + escapeHtml(t) + '</span>';
    }).join("");
    $modalToolsSection.style.display = "none";
    $modalBackstoryS.style.display = "none";

    // Show modal immediately
    $modalOverlay.classList.add("active");

    // Fetch enriched card data
    try {
      var card;
      if (cardCache[personaId]) {
        card = cardCache[personaId];
      } else if (cardUrl) {
        var resp = await fetch(cardUrl);
        if (resp.ok) {
          card = await resp.json();
          cardCache[personaId] = card;
        }
      }

      if (card) {
        if (card.role) $modalRole.textContent = card.role;
        if (card.class_id) $modalClassBadge.textContent = card.class_id;

        if (card.stats) renderModalStats(card.stats);

        // Style & Tone tags
        var tagsHtml = "";
        if (card.style_tags) {
          tagsHtml += card.style_tags.map(function (t) {
            return '<span class="modal-tag style">' + escapeHtml(t) + '</span>';
          }).join("");
        }
        if (card.tone_tags) {
          tagsHtml += card.tone_tags.map(function (t) {
            return '<span class="modal-tag tone">' + escapeHtml(t) + '</span>';
          }).join("");
        }
        if (card.tags) {
          tagsHtml += card.tags.map(function (t) {
            return '<span class="modal-tag">' + escapeHtml(t) + '</span>';
          }).join("");
        }
        if (tagsHtml) $modalStyleTags.innerHTML = tagsHtml;

        // Tools
        if (card.tools && card.tools.length > 0) {
          $modalToolsSection.style.display = "";
          $modalTools.innerHTML = card.tools.map(function (t) {
            return '<span class="modal-tag tool">' + escapeHtml(t) + '</span>';
          }).join("");
        }

        // Backstory
        if (card.backstory) {
          $modalBackstoryS.style.display = "";
          $modalBackstory.textContent = card.backstory;
        }
      }
    } catch (err) {
      console.warn("Could not fetch card data:", err);
    }
  }

  function renderModalStats(stats) {
    var level = stats.level || 1;
    $modalLevel.textContent = "LV " + level;

    var statNames = ["charisma", "elegance", "confidence", "warmth"];
    var html = "";
    statNames.forEach(function (name) {
      var val = stats[name] || 0;
      html += [
        '<div class="stat-row">',
        '  <span class="stat-label">' + name + '</span>',
        '  <div class="stat-bar-bg">',
        '    <div class="stat-bar-fill ' + name + '" style="width:' + Math.min(val, 100) + '%"></div>',
        '  </div>',
        '  <span class="stat-value">' + val + '</span>',
        '</div>',
      ].join("");
    });
    $modalStats.innerHTML = html;
  }

  window.__openDetails = openDetailModal;

  // ── Event listeners ────────────────────────────────────────────

  var debounceTimer;
  $search.addEventListener("input", function () {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(render, 200);
  });
  $filterTag.addEventListener("change", render);
  $filterRate.addEventListener("change", render);
  $sort.addEventListener("change", render);

  // Wire up Load More button
  var $loadMoreBtn = document.getElementById("load-more-btn");
  if ($loadMoreBtn) $loadMoreBtn.addEventListener("click", loadMoreItems);

  // ── Init ───────────────────────────────────────────────────────
  fetchRegistry();
})();
