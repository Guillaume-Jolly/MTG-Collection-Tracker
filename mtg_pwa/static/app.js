const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

const DECKS_PAGE_SIZE = 20;

const state = {
  collection: null,
  currentTab: "search",
  previousTab: "search",
  decks: {
    page: 1,
    total: 0,
    totalPages: 1,
    loading: false,
    searchTimer: null,
  },
  collectionBrowse: {
    level: "blocks",
    setCode: null,
    setName: null,
    sectionCode: null,
    sectionLabel: null,
    sortPrimary: "price_desc",
    sortSecondary: "",
    multiSort: false,
    cardsTotal: 0,
    cardSize: 110,
  },
};

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Erreur API");
  }
  return payload;
}

function money(value) {
  if (value === null || value === undefined) {
    return "Prix inconnu";
  }
  return eur.format(value);
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("visible");
  window.setTimeout(() => node.classList.remove("visible"), 2400);
}

function setLoading(node, loading, label) {
  node.disabled = loading;
  if (loading) {
    node.dataset.previousLabel = node.textContent;
    node.textContent = label || "Chargement...";
  } else if (node.dataset.previousLabel) {
    node.textContent = node.dataset.previousLabel;
    delete node.dataset.previousLabel;
  }
}

function switchTab(tab) {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
  });
  document.querySelectorAll(".screen").forEach((screen) => {
    screen.classList.toggle("active", screen.id === `screen-${tab}`);
  });
  state.currentTab = tab;
  document.body.classList.toggle("collection-full-width", tab === "collection");
  if (tab === "decks") {
    loadDeckExtensions()
      .then(() => loadDecks(state.decks.page))
      .catch((error) => toast(error.message));
  }
  if (tab === "collection") {
    showCollectionLevel(state.collectionBrowse.level).catch((error) => toast(error.message));
  }
}

function openCardScreen() {
  if (state.currentTab !== "prices") {
    state.previousTab = state.currentTab;
  }
  switchTab("prices");
}

function backFromCard() {
  switchTab(state.previousTab || "search");
}

function priceLabel(price) {
  if (!price) {
    return `<div class="price">Prix EUR indisponible</div>`;
  }
  const fallback = price.is_fallback ? `<span class="fallback">dernier prix trouve</span>` : "";
  return `<div class="price">${money(price.price)} <span class="meta">${escapeHtml(price.finish)}</span> ${fallback}</div>`;
}

function cardImage(card) {
  if (!card.image_url) {
    return `<div class="card-image"></div>`;
  }
  return `<img class="card-image" src="${card.image_url}" alt="${escapeHtml(card.printed_name || card.name)}" loading="lazy" />`;
}

function detailImage(card) {
  const source = card.image_large_url || card.image_url;
  if (!source) {
    return `<div class="detail-card-image"></div>`;
  }
  return `<img class="detail-card-image" src="${source}" alt="${escapeHtml(card.printed_name || card.name)}" loading="lazy" />`;
}

function deckPreviewImage(card) {
  const source = card.image_large_url || card.image_url;
  if (!source) {
    return `<div class="deck-preview-card-image"></div>`;
  }
  return `<img class="deck-preview-card-image" src="${source}" alt="${escapeHtml(card.printed_name || card.name)}" loading="lazy" />`;
}

function renderSearchResults(cards) {
  const node = $("#searchResults");
  if (!cards.length) {
    node.innerHTML = `<div class="panel"><p class="muted">Aucun resultat.</p></div>`;
    return;
  }
  node.innerHTML = cards.map(renderSearchCard).join("");
  bindCardOpen(node);
  bindDetailButtons(node);
  node.querySelectorAll("[data-add]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      addCard(button.dataset.cardId, button.dataset.finish, button);
    });
  });
}

function renderSearchCard(card) {
  const finishes = (card.finishes && card.finishes.length ? card.finishes : ["nonfoil"]).filter((finish) =>
    ["nonfoil", "foil", "etched"].includes(finish),
  );
  return `
    <article class="card-result openable-card" data-card-open data-card-id="${card.id}" data-finish="${card.display_finish || card.price?.finish || "nonfoil"}" role="button" tabindex="0">
      ${cardImage(card)}
      <div class="card-body">
        <h3 class="card-title">${escapeHtml(card.printed_name || card.name)}</h3>
        <div class="meta">${escapeHtml(card.set_name || card.set || "")} #${escapeHtml(card.collector_number || "")}</div>
        <div class="meta">${escapeHtml(card.lang || "")} - ${escapeHtml(card.rarity || "")} - ${escapeHtml(card.finishes?.join(", ") || "")}</div>
        ${priceLabel(card.price)}
        <div class="actions">
          <button class="secondary" data-detail data-card-id="${card.id}" data-finish="${card.display_finish || card.price?.finish || "nonfoil"}">Fiche</button>
          ${finishes
            .map(
              (finish) =>
                `<button class="secondary" data-add data-card-id="${card.id}" data-finish="${finish}">+ ${finish}</button>`,
            )
            .join("")}
        </div>
      </div>
    </article>
  `;
}

async function addCard(scryfallId, finish, button) {
  try {
    setLoading(button, true, "Ajout...");
    const collection = await api("/api/collection", {
      method: "POST",
      body: JSON.stringify({ scryfall_id: scryfallId, finish, quantity: 1 }),
    });
    state.collection = collection;
    renderCollection(collection);
    toast("Carte ajoutee");
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(button, false);
  }
}

async function loadCollection() {
  const collection = await api("/api/collection/summary");
  state.collection = collection;
  renderCollection(collection);
}

function renderDeckResults(decks) {
  const node = $("#deckResults");
  if (!decks.length) {
    node.innerHTML = `<div class="panel"><p class="muted">Aucun deck trouve.</p></div>`;
    return;
  }
  node.innerHTML = decks.map(renderDeckCard).join("");
  node.querySelectorAll("[data-preview-deck]").forEach((button) => {
    button.addEventListener("click", () => showDeckDetail(button.dataset.fileName, button));
  });
  node.querySelectorAll("[data-import-deck]").forEach((button) => {
    button.addEventListener("click", () => importDeck(button.dataset.fileName, button));
  });
}

function renderDeckListMeta(meta) {
  const node = $("#deckListMeta");
  if (!meta.total) {
    node.textContent = "";
    return;
  }
  const start = (meta.page - 1) * meta.page_size + 1;
  const end = Math.min(meta.page * meta.page_size, meta.total);
  node.textContent = `${start}-${end} sur ${meta.total} deck(s)`;
}

function renderDeckPagination(meta) {
  const node = $("#deckPagination");
  if (!meta || meta.total_pages <= 1) {
    node.innerHTML = "";
    return;
  }

  const pages = paginationPages(meta.page, meta.total_pages);
  node.innerHTML = `
    <button class="secondary page-btn" data-page="${meta.page - 1}" ${meta.page <= 1 ? "disabled" : ""} aria-label="Page precedente">&#8249;</button>
    ${pages
      .map((entry) =>
        entry === "..."
          ? `<span class="page-ellipsis">...</span>`
          : `<button class="secondary page-btn ${entry === meta.page ? "active" : ""}" data-page="${entry}" ${entry === meta.page ? 'aria-current="page"' : ""}>${entry}</button>`,
      )
      .join("")}
    <button class="secondary page-btn" data-page="${meta.page + 1}" ${meta.page >= meta.total_pages ? "disabled" : ""} aria-label="Page suivante">&#8250;</button>
  `;

  node.querySelectorAll("[data-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const page = Number(button.dataset.page);
      if (!Number.isNaN(page)) {
        loadDecks(page).catch((error) => toast(error.message));
      }
    });
  });
}

function paginationPages(current, total) {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }
  const pages = new Set([1, total, current, current - 1, current + 1]);
  const ordered = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
  const result = [];
  for (let index = 0; index < ordered.length; index += 1) {
    if (index > 0 && ordered[index] - ordered[index - 1] > 1) {
      result.push("...");
    }
    result.push(ordered[index]);
  }
  return result;
}

function deckFilterParams() {
  return new URLSearchParams({
    commander_only: $("#commanderOnlyInput").checked ? "true" : "false",
    hide_collector: $("#hideCollectorInput").checked ? "true" : "false",
  });
}

function deckSearchParams(page = 1) {
  return new URLSearchParams({
    q: $("#deckSearchInput").value.trim(),
    page: String(page),
    page_size: String(DECKS_PAGE_SIZE),
    commander_only: $("#commanderOnlyInput").checked ? "true" : "false",
    hide_collector: $("#hideCollectorInput").checked ? "true" : "false",
    extension: $("#deckExtensionInput").value,
    sort: $("#deckSortInput").value,
  });
}

async function loadDeckExtensions() {
  const select = $("#deckExtensionInput");
  const previous = select.value;
  const payload = await api(`/api/decks/extensions?${deckFilterParams().toString()}`);
  const extensions = payload.extensions || [];
  select.innerHTML = `<option value="">Toutes les extensions</option>${extensions
    .map((entry) => {
      const code = entry.code || entry;
      const name = entry.name || code;
      const label = name !== code ? `${name} (${code})` : code;
      return `<option value="${escapeHtml(code)}">${escapeHtml(label)}</option>`;
    })
    .join("")}`;
  if (previous && extensions.some((entry) => (entry.code || entry) === previous)) {
    select.value = previous;
  }
}

async function loadDecks(page = 1) {
  if (state.decks.loading) {
    return;
  }
  state.decks.loading = true;
  state.decks.page = page;
  const node = $("#deckResults");
  node.innerHTML = `<div class="panel"><p class="muted">Chargement des decks...</p></div>`;

  try {
    const payload = await api(`/api/decks/search?${deckSearchParams(page).toString()}`);
    state.decks.total = payload.total || 0;
    state.decks.totalPages = payload.total_pages || 1;
    renderDeckListMeta(payload);
    renderDeckResults(payload.decks || []);
    renderDeckPagination(payload);
    if (page > 1) {
      $("#deckResults").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } finally {
    state.decks.loading = false;
  }
}

function scheduleDeckReload() {
  window.clearTimeout(state.decks.searchTimer);
  state.decks.searchTimer = window.setTimeout(() => {
    loadDecks(1).catch((error) => toast(error.message));
  }, 300);
}

function toggleDeckPanel(button, panel) {
  const open = panel.classList.toggle("hidden") === false;
  button.setAttribute("aria-expanded", open ? "true" : "false");
}

function renderDeckCard(deck) {
  return `
    <article class="deck-card">
      <h3>${escapeHtml(deck.name)}</h3>
      <div class="meta">${escapeHtml(deck.type || "")} - ${escapeHtml(deck.code || "")} - ${escapeHtml(deck.release_date || "")}</div>
      <div class="meta">${escapeHtml(deck.file_name || "")}</div>
      ${renderDeckMenuPrice(deck.price_estimate)}
      <div class="actions">
        <button class="secondary" data-preview-deck data-file-name="${escapeHtml(deck.file_name)}">Voir le deck</button>
        <button class="primary" data-import-deck data-file-name="${escapeHtml(deck.file_name)}">Ajouter toutes les cartes</button>
      </div>
    </article>
  `;
}

function renderDeckMenuPrice(priceEstimate) {
  if (!priceEstimate) {
    return `<div class="deck-menu-price"><strong>Prix: N/A</strong></div>`;
  }
  return `
    <div class="deck-menu-price">
      <strong>${money(priceEstimate.total_eur || 0)}</strong>
      <span>${priceEstimate.priced_cards || 0} avec prix, ${priceEstimate.missing_cards || 0} sans prix${priceEstimate.latest_date ? ` - ${escapeHtml(priceEstimate.latest_date)}` : ""}</span>
    </div>
  `;
}

async function showDeckDetail(fileName, button) {
  try {
    setLoading(button, true, "Chargement...");
    $("#deckPreview").innerHTML = "";
    const payload = await api(`/api/decks/detail?file_name=${encodeURIComponent(fileName)}`);
    renderDeckPreview(payload);
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(button, false);
  }
}

function renderDeckPreview(payload) {
  const deck = payload.deck;
  const commanders = payload.commanders || [];
  const cardsBySection = payload.cards_by_section || {};
  const valuation = payload.valuation || {};
  const commander = commanders[0];
  $("#deckPreview").innerHTML = `
    <section class="panel deck-preview">
      <div class="deck-preview-hero">
        ${commander ? deckPreviewImage(commander) : `<div class="deck-preview-card-image"></div>`}
        <div>
          <p class="eyebrow">Previsualisation</p>
          <h2>${escapeHtml(deck.name)}</h2>
          <div class="meta">${escapeHtml(deck.type || "")} - ${escapeHtml(deck.code || "")} - ${escapeHtml(deck.release_date || "")}</div>
          <div class="meta">${deck.card_count} cartes, ${deck.card_lines} lignes, ${deck.foil_count} foil</div>
          ${commanders.length ? `<div class="price">Commander: ${commanders.map((card) => escapeHtml(card.name)).join(", ")}</div>` : ""}
          ${renderDeckValuationSummary(valuation)}
          <div class="actions">
            <button class="primary" data-import-deck data-file-name="${escapeHtml(deck.file_name)}">Importer ce deck</button>
          </div>
        </div>
      </div>
      ${renderDeckHistory(valuation)}
      ${renderDeckSection("Commander", cardsBySection.commander || [])}
      ${renderDeckSection("Main deck", cardsBySection.mainBoard || [])}
      ${renderDeckSection("Sideboard", cardsBySection.sideBoard || [])}
    </section>
  `;
  $("#deckPreview").querySelectorAll("[data-import-deck]").forEach((button) => {
    button.addEventListener("click", () => importDeck(button.dataset.fileName, button));
  });
  bindCardOpen($("#deckPreview"));
  $("#deckPreview").scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderDeckValuationSummary(valuation) {
  return `
    <div class="deck-value">
      <span>Prix estime</span>
      <strong>${money(valuation.current_total_eur || 0)}</strong>
      <small>${valuation.priced_cards || 0} carte(s) avec prix, ${valuation.missing_cards || 0} sans prix</small>
    </div>
  `;
}

function renderDeckHistory(valuation) {
  const history = valuation.history || [];
  const missingLines = valuation.missing_lines || [];
  return `
    <div class="deck-section">
      <h3>Suivi prix du deck</h3>
      <p class="helper-text">Somme des prix Cardmarket EUR disponibles carte par carte. Les cartes sans prix sont comptees a part.</p>
      ${renderDeckChart(history)}
      ${
        history.length
          ? `<div class="history-list">${history
              .slice(-8)
              .reverse()
              .map(
                (point) =>
                  `<div class="history-row"><span>${escapeHtml(point.snapshot_date)} (${point.missing_cards} sans prix)</span><strong>${money(point.total_eur)}</strong></div>`,
              )
              .join("")}</div>`
          : `<p class="muted">Pas encore d'historique MTGJSON Cardmarket EUR pour ce deck.</p>`
      }
      ${
        missingLines.length
          ? `<details class="missing-prices"><summary>${missingLines.length} ligne(s) sans prix individuel</summary>${missingLines
              .slice(0, 40)
              .map(
                (line) =>
                  `<div class="deck-line openable-card" data-card-open data-card-id="${escapeHtml(line.scryfall_id)}" data-finish="${escapeHtml(line.finish)}" role="button" tabindex="0"><strong>${line.quantity}x ${escapeHtml(line.name)}</strong><span>${escapeHtml(line.set_code)} #${escapeHtml(line.collector_number)} - ${escapeHtml(line.finish)} - ${escapeHtml(line.reason)}</span></div>`,
              )
              .join("")}</details>`
          : ""
      }
    </div>
  `;
}

function renderDeckChart(history) {
  if (!history.length) {
    return `<div class="chart"></div>`;
  }
  return renderChart(
    history.map((point) => ({
      snapshot_date: point.snapshot_date,
      price: point.total_eur,
    })),
  );
}

function renderDeckSection(title, cards) {
  if (!cards.length) {
    return "";
  }
  return `
    <div class="deck-section">
      <h3>${escapeHtml(title)} (${cards.reduce((sum, card) => sum + Number(card.quantity || 0), 0)})</h3>
      <div class="deck-card-list">
        ${cards
          .map(
            (card) => `
              <div class="deck-line openable-card" data-card-open data-card-id="${escapeHtml(card.scryfall_id)}" data-finish="${escapeHtml(card.finish)}" role="button" tabindex="0">
                <strong>${card.quantity}x ${escapeHtml(card.name)}</strong>
                <span>${escapeHtml(card.set_code)} #${escapeHtml(card.collector_number)} - ${escapeHtml(card.finish)}</span>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

async function importDeck(fileName, button) {
  try {
    setLoading(button, true, "Import...");
    const collection = await api("/api/decks/import", {
      method: "POST",
      body: JSON.stringify({ file_name: fileName }),
    });
    state.collection = collection;
    renderCollection(collection);
    const info = collection.deck_import;
    toast(`${info.imported_cards} carte(s) ajoutee(s) depuis ${info.deck.name}`);
    switchTab("collection");
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(button, false);
  }
}

async function startCommanderPreload(button) {
  try {
    setLoading(button, true, "Prechargement...");
    const status = await api("/api/preload/commander-prices", {
      method: "POST",
      body: JSON.stringify({}),
    });
    renderPreloadStatus(status);
    pollPreloadStatus();
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(button, false);
  }
}

async function pollPreloadStatus() {
  try {
    const status = await api("/api/preload/commander-prices");
    renderPreloadStatus(status);
    if (status.running) {
      window.setTimeout(pollPreloadStatus, 2500);
    }
  } catch (error) {
    $("#preloadStatus").textContent = `Statut: ${error.message}`;
  }
}

function renderPreloadStatus(status) {
  const parts = [];
  if (status.running) {
    parts.push("en cours");
  } else if (status.finished_at) {
    parts.push("termine");
  } else {
    parts.push("non lance");
  }
  if (status.decks_total) {
    parts.push(`${status.decks_processed || 0}/${status.decks_total} decks`);
  }
  if (status.unique_uuids) {
    parts.push(`${status.unique_uuids} cartes uniques`);
  }
  if (status.scryfall_cards_cached) {
    parts.push(`${status.scryfall_cards_cached} cartes Scryfall`);
  }
  if (status.points) {
    parts.push(`${status.points} points prix`);
  }
  if (status.error) {
    parts.push(`erreur: ${status.error}`);
  }
  $("#preloadStatus").textContent = `Statut: ${parts.join(" - ")}`;
}

function renderCollection(collection) {
  const summary = collection.summary || {};
  $("#headerTotal").textContent = money(summary.estimated_value_eur || 0);
  state.collection = collection;
}

function formatSetStats(entry) {
  const owned = entry.owned_cards || 0;
  const total = entry.total_cards || 0;
  const ownedValue = money(entry.owned_value_eur || 0);
  const totalValue = entry.total_value_eur != null ? money(entry.total_value_eur) : "—";
  return `${owned} / ${total} cartes - ${ownedValue} / ${totalValue}`;
}

async function loadCollectionBlocks() {
  $("#collectionBlocksView").innerHTML = `<div class="panel"><p class="muted">Chargement des blocs...</p></div>`;
  const payload = await api("/api/collection/blocks");
  renderCollectionBlocks(payload.categories || []);
}

function renderCollectionBlocks(categories) {
  const node = $("#collectionBlocksView");
  node.innerHTML = categories
    .map(
      (category) => `
      <section class="block-category">
        <button class="block-category-header" type="button" data-toggle-category="${escapeHtml(category.id)}">
          <span>${escapeHtml(category.label)}</span>
          <span class="block-count">${category.count}</span>
        </button>
        <div class="block-grid" id="category-${escapeHtml(category.id)}">
          ${category.sets.map(renderBlockTile).join("")}
        </div>
      </section>
    `,
    )
    .join("");

  node.querySelectorAll("[data-open-set]").forEach((button) => {
    button.addEventListener("click", () => openCollectionSet(button.dataset.setCode, button.dataset.setName));
  });
  node.querySelectorAll("[data-toggle-category]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = $(`#category-${button.dataset.toggleCategory}`);
      target.classList.toggle("collapsed");
    });
  });
}

function renderBlockTile(entry) {
  const ownedClass = entry.owned_cards ? "block-tile owned" : "block-tile";
  return `
    <button class="${ownedClass}" type="button" data-open-set data-set-code="${escapeHtml(entry.code)}" data-set-name="${escapeHtml(entry.name)}">
      <span class="block-tile-code">${escapeHtml(entry.code)}</span>
      <strong>${escapeHtml(entry.name)}</strong>
      <span class="block-tile-meta">${formatSetStats(entry)}</span>
    </button>
  `;
}

async function openCollectionSet(setCode, setName) {
  state.collectionBrowse.level = "set";
  state.collectionBrowse.setCode = setCode;
  state.collectionBrowse.setName = setName;
  state.collectionBrowse.sectionCode = null;
  state.collectionBrowse.sectionLabel = null;
  await showCollectionLevel("set");
}

async function openCollectionSection(sectionCode, sectionLabel) {
  state.collectionBrowse.level = "cards";
  state.collectionBrowse.sectionCode = sectionCode;
  state.collectionBrowse.sectionLabel = sectionLabel;
  await showCollectionLevel("cards");
}

async function showCollectionLevel(level) {
  state.collectionBrowse.level = level;
  hideCollectionPriceProgress();
  $("#collectionBlocksView").classList.toggle("hidden", level !== "blocks");
  $("#collectionSetView").classList.toggle("hidden", level !== "set");
  $("#collectionCardsView").classList.toggle("hidden", level !== "cards");
  $("#collectionNav").classList.toggle("hidden", level === "blocks");

  if (level === "blocks") {
    $("#collectionNavTitle").textContent = "Blocs";
    $("#collectionNavEyebrow").textContent = "Collection";
    await loadCollectionBlocks();
    return;
  }

  if (level === "set") {
    $("#collectionNavTitle").textContent = state.collectionBrowse.setName || state.collectionBrowse.setCode;
    $("#collectionNavEyebrow").textContent = "Extension";
    $("#collectionSetView").innerHTML = `<div class="panel"><p class="muted">Chargement...</p></div>`;
    const payload = await api(`/api/collection/${encodeURIComponent(state.collectionBrowse.setCode)}`);
    renderCollectionSet(payload);
    return;
  }

  $("#collectionNavTitle").textContent = state.collectionBrowse.sectionLabel || state.collectionBrowse.sectionCode;
  $("#collectionNavEyebrow").textContent = state.collectionBrowse.setName || "";
  await loadCollectionCards();
}

function buildCollectionSortParam() {
  const browse = state.collectionBrowse;
  const primary = browse.sortPrimary || "price_desc";
  if (browse.multiSort && browse.sortSecondary) {
    return `${primary},${browse.sortSecondary}`;
  }
  return primary;
}

const COLLECTION_SORT_OPTIONS = [
  { value: "price_desc", label: "Prix decroissant" },
  { value: "price_asc", label: "Prix croissant" },
  { value: "number_asc", label: "Numero croissant" },
  { value: "number_desc", label: "Numero decroissant" },
  { value: "name_asc", label: "Nom A-Z" },
  { value: "name_desc", label: "Nom Z-A" },
];

function renderSortOptions(selectedValue, includeEmpty = false) {
  const emptyOption = includeEmpty ? `<option value="">—</option>` : "";
  return (
    emptyOption +
    COLLECTION_SORT_OPTIONS.map(
      (option) =>
        `<option value="${option.value}" ${option.value === selectedValue ? "selected" : ""}>${option.label}</option>`,
    ).join("")
  );
}

const CARD_SIZE_STORAGE_KEY = "mtg_catalog_card_min";
const DEFAULT_CATALOG_CARD_SIZE = 110;
const MIN_CATALOG_CARD_SIZE = 80;
const MAX_CATALOG_CARD_SIZE = 200;

function applyCatalogCardSize(sizePx) {
  const size = Math.max(MIN_CATALOG_CARD_SIZE, Math.min(MAX_CATALOG_CARD_SIZE, sizePx));
  state.collectionBrowse.cardSize = size;
  document.documentElement.style.setProperty("--catalog-card-min", `${size}px`);
  document.documentElement.style.setProperty("--catalog-price-max", `${Math.round(size * 0.115)}px`);
  document.documentElement.style.setProperty("--catalog-price-min", `${Math.max(10, Math.round(size * 0.085))}px`);
  document.documentElement.style.setProperty("--catalog-qty-btn", `${Math.max(1.15, Math.round(size * 0.0122 * 100) / 100)}rem`);
  localStorage.setItem(CARD_SIZE_STORAGE_KEY, String(size));
  const slider = $("#catalogCardSizeInput");
  if (slider && Number(slider.value) !== size) {
    slider.value = String(size);
  }
  const cardsView = $("#collectionCardsView");
  if (cardsView && !cardsView.classList.contains("hidden")) {
    fitCatalogPriceLabels(cardsView);
  }
}

function initCatalogCardSize() {
  const stored = parseInt(localStorage.getItem(CARD_SIZE_STORAGE_KEY) || "", 10);
  applyCatalogCardSize(Number.isFinite(stored) ? stored : DEFAULT_CATALOG_CARD_SIZE);
}

function waitForPaint() {
  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

async function loadCollectionCards() {
  const sort = buildCollectionSortParam();
  $("#collectionCardsView").innerHTML = `<div class="panel"><p class="muted">Chargement...</p></div>`;
  const payload = await api(
    `/api/collection/${encodeURIComponent(state.collectionBrowse.sectionCode)}/cards?sort=${encodeURIComponent(sort)}`,
  );
  renderCollectionCards(payload);
}

async function refreshCollectionPrices(scope, onProgress) {
  const browse = state.collectionBrowse;
  const baseBody =
    scope === "block"
      ? { scope: "block", set_code: browse.setCode }
      : { scope: "section", section_code: browse.sectionCode, set_code: browse.setCode };

  let offset = 0;
  let total = 0;
  let refreshed = 0;
  let errors = 0;

  while (true) {
    const payload = await api("/api/collection/refresh-prices", {
      method: "POST",
      body: JSON.stringify({ ...baseBody, offset, limit: 75 }),
    });
    const result = payload.refresh || {};
    total = result.cards_total || total;
    refreshed += result.cards_refreshed || 0;
    errors += result.errors || 0;
    offset = result.next_offset ?? offset;
    if (onProgress) {
      onProgress({ done: Math.min(offset, total), total, errors });
    }
    if (result.done === true || result.next_offset == null || offset >= total) {
      return { cards_total: total, cards_refreshed: refreshed, errors };
    }
  }
}

function setCollectionPriceProgress(done, total, title = "Chargement des prix") {
  const wrap = $("#collectionPriceProgress");
  const bar = $("#collectionPriceProgressBar");
  const label = $("#collectionPriceProgressLabel");
  const titleNode = $("#collectionPriceProgressTitle");
  if (!wrap || !bar || !label) {
    return;
  }
  const safeTotal = Math.max(total || 0, 1);
  const safeDone = Math.min(Math.max(done || 0, 0), safeTotal);
  const percent = Math.max(4, Math.round((safeDone / safeTotal) * 100));
  wrap.classList.remove("hidden");
  bar.style.width = `${percent}%`;
  label.textContent = `${safeDone} / ${safeTotal} (${percent}%)`;
  if (titleNode) {
    titleNode.textContent = title;
  }
}

function hideCollectionPriceProgress() {
  const wrap = $("#collectionPriceProgress");
  if (!wrap) {
    return;
  }
  wrap.classList.add("hidden");
  const bar = $("#collectionPriceProgressBar");
  if (bar) {
    bar.style.width = "0%";
  }
}

function fitCatalogPriceLabels(root = document) {
  const maxPx = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--catalog-price-max")) || 12;
  const minPx = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--catalog-price-min")) || 10;
  const nodes = root.querySelectorAll ? root.querySelectorAll(".catalog-card-price") : [];
  nodes.forEach((el) => {
    el.classList.remove("is-stacked");
    el.style.fontSize = `${maxPx}px`;
    el.style.lineHeight = "1.15";
    let size = maxPx;
    while (el.scrollWidth > el.clientWidth && size > minPx) {
      size -= 0.5;
      el.style.fontSize = `${size}px`;
    }
    if (el.scrollWidth > el.clientWidth) {
      el.classList.add("is-stacked");
      el.style.fontSize = `${minPx}px`;
      el.style.lineHeight = "1.05";
      const nonfoil = el.dataset.priceNonfoil || "";
      const foil = el.dataset.priceFoil || "";
      if (nonfoil && foil) {
        el.textContent = `${nonfoil}\n${foil}`;
      }
    }
  });
}

let catalogPriceFitObserver = null;

function observeCatalogPriceFit(node) {
  if (catalogPriceFitObserver) {
    catalogPriceFitObserver.disconnect();
  }
  fitCatalogPriceLabels(node);
  if (typeof ResizeObserver === "undefined") {
    return;
  }
  catalogPriceFitObserver = new ResizeObserver(() => fitCatalogPriceLabels(node));
  const grid = node.querySelector(".catalog-card-grid");
  if (grid) {
    catalogPriceFitObserver.observe(grid);
  }
}

function formatCatalogPrice(card) {
  const nonfoil = card.price_nonfoil;
  const foil = card.price_foil;
  if (nonfoil != null && foil != null) {
    return `${money(nonfoil)} · ${money(foil)}`;
  }
  if (nonfoil != null) {
    return money(nonfoil);
  }
  if (foil != null) {
    return money(foil);
  }
  return "—";
}

async function adjustCollectionQty(scryfallId, finish, delta) {
  const payload = await api("/api/collection/adjust", {
    method: "POST",
    body: JSON.stringify({ scryfall_id: scryfallId, finish, delta }),
  });
  renderCollection(payload);
  return payload;
}

function renderCollectionSet(payload) {
  const node = $("#collectionSetView");
  node.innerHTML = `
    <div class="collection-set-toolbar">
      <p class="muted">Sous-sections de ${escapeHtml(payload.set?.name || state.collectionBrowse.setName || "")}</p>
      <button class="secondary" id="refreshSetPrices" type="button">Charger les prix du bloc</button>
    </div>
    <div class="set-section-grid">
      ${payload.sections
        .map(
          (section) => `
          <button class="set-section-tile" type="button" data-open-section data-section-code="${escapeHtml(section.code)}" data-section-label="${escapeHtml(section.label)}">
            <strong>${escapeHtml(section.label)}</strong>
            <span>${formatSetStats(section)}</span>
          </button>
        `,
        )
        .join("")}
    </div>
  `;
  node.querySelector("#refreshSetPrices")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const estimatedTotal = payload.sections.reduce((sum, section) => sum + (section.total_cards || 0), 0) || 1;
    try {
      setLoading(button, true, "Chargement...");
      setCollectionPriceProgress(0, estimatedTotal, "Chargement des prix du bloc");
      await waitForPaint();
      const refresh = await refreshCollectionPrices("block", ({ done, total }) =>
        setCollectionPriceProgress(done, total, "Chargement des prix du bloc"),
      );
      toast(`${refresh.cards_refreshed || 0} / ${refresh.cards_total || 0} prix charges`);
      setCollectionPriceProgress(refresh.cards_total || 0, refresh.cards_total || 1, "Chargement des prix du bloc");
      await new Promise((resolve) => setTimeout(resolve, 800));
      invalidateCollectionBlocksCache();
      const updated = await api(`/api/collection/${encodeURIComponent(state.collectionBrowse.setCode)}`);
      renderCollectionSet(updated);
    } catch (error) {
      toast(error.message);
    } finally {
      hideCollectionPriceProgress();
      setLoading(button, false);
    }
  });
  node.querySelectorAll("[data-open-section]").forEach((button) => {
    button.addEventListener("click", () =>
      openCollectionSection(button.dataset.sectionCode, button.dataset.sectionLabel),
    );
  });
}

function invalidateCollectionBlocksCache() {
  state.collectionBrowse.blocksStale = true;
}

function renderCollectionCards(payload) {
  const summary = payload.summary || {};
  state.collectionBrowse.cardsTotal = summary.total_cards || 0;
  const browse = state.collectionBrowse;
  const node = $("#collectionCardsView");
  const unavailable = payload.unavailable
    ? `<div class="panel"><p class="muted">Catalogue indisponible pour cette section (donnees MTGJSON absentes).</p></div>`
    : "";
  node.innerHTML = `
    <div class="collection-cards-toolbar">
      <div class="collection-cards-summary">
        ${summary.owned_unique || 0} (${summary.owned_cards || 0}) / ${summary.total_cards || 0} cartes -
        ${money(summary.owned_value_eur || 0)} / ${money(summary.total_value_eur || 0)}
      </div>
      <div class="collection-cards-controls">
        <label class="collection-cards-sort">
          <span>Trier</span>
          <select id="collectionSortPrimary" aria-label="Tri principal">
            ${renderSortOptions(browse.sortPrimary)}
          </select>
        </label>
        <label class="collection-cards-sort check-row collection-multi-sort">
          <input id="collectionMultiSort" type="checkbox" ${browse.multiSort ? "checked" : ""} />
          Tri multiple
        </label>
        <label class="collection-cards-sort ${browse.multiSort ? "" : "hidden"}" id="collectionSecondarySortWrap">
          <span>Puis</span>
          <select id="collectionSortSecondary" aria-label="Tri secondaire" ${browse.multiSort ? "" : "disabled"}>
            ${renderSortOptions(browse.sortSecondary, true)}
          </select>
        </label>
        <button class="secondary" id="refreshSectionPrices" type="button">Charger les prix</button>
        <label class="collection-card-size">
          <span>Taille</span>
          <input
            id="catalogCardSizeInput"
            type="range"
            min="${MIN_CATALOG_CARD_SIZE}"
            max="${MAX_CATALOG_CARD_SIZE}"
            step="5"
            value="${state.collectionBrowse.cardSize || DEFAULT_CATALOG_CARD_SIZE}"
          />
        </label>
      </div>
    </div>
    ${unavailable}
    <div class="catalog-card-grid">
      ${(payload.cards || []).map(renderCatalogCard).join("")}
    </div>
  `;

  const applySort = () => {
    browse.sortPrimary = $("#collectionSortPrimary").value;
    browse.sortSecondary = $("#collectionSortSecondary").value;
    browse.multiSort = $("#collectionMultiSort").checked;
    loadCollectionCards().catch((error) => toast(error.message));
  };

  node.querySelector("#collectionSortPrimary")?.addEventListener("change", applySort);
  node.querySelector("#collectionSortSecondary")?.addEventListener("change", applySort);
  node.querySelector("#collectionMultiSort")?.addEventListener("change", (event) => {
    browse.multiSort = event.currentTarget.checked;
    const wrap = node.querySelector("#collectionSecondarySortWrap");
    const secondary = node.querySelector("#collectionSortSecondary");
    wrap?.classList.toggle("hidden", !browse.multiSort);
    if (secondary) {
      secondary.disabled = !browse.multiSort;
    }
    if (!browse.multiSort) {
      browse.sortSecondary = "";
      if (secondary) {
        secondary.value = "";
      }
    }
    loadCollectionCards().catch((error) => toast(error.message));
  });

  node.querySelector("#catalogCardSizeInput")?.addEventListener("input", (event) => {
    applyCatalogCardSize(Number(event.currentTarget.value));
  });

  node.querySelector("#refreshSectionPrices")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const estimatedTotal = state.collectionBrowse.cardsTotal || summary.total_cards || 1;
    try {
      setLoading(button, true, "Chargement...");
      setCollectionPriceProgress(0, estimatedTotal);
      await waitForPaint();
      const refresh = await refreshCollectionPrices("section", ({ done, total }) => setCollectionPriceProgress(done, total));
      toast(`${refresh.cards_refreshed || 0} / ${refresh.cards_total || 0} prix charges`);
      setCollectionPriceProgress(refresh.cards_total || 0, refresh.cards_total || 1);
      await new Promise((resolve) => setTimeout(resolve, 800));
      await loadCollectionCards();
    } catch (error) {
      toast(error.message || "Erreur lors du chargement des prix");
    } finally {
      hideCollectionPriceProgress();
      setLoading(button, false);
    }
  });

  node.querySelectorAll("[data-qty-delta]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const target = event.currentTarget;
      const cardNode = target.closest(".catalog-card");
      if (!cardNode) {
        return;
      }
      const delta = Number(target.dataset.qtyDelta || 0);
      try {
        setLoading(target, true, delta > 0 ? "+" : "-");
        await adjustCollectionQty(cardNode.dataset.cardId, cardNode.dataset.finish || "nonfoil", delta);
        invalidateCollectionBlocksCache();
        await loadCollectionCards();
      } catch (error) {
        toast(error.message);
      } finally {
        setLoading(target, false);
      }
    });
  });

  bindCardOpen(node);
  observeCatalogPriceFit(node);
}

function renderCatalogCard(card) {
  const ownedClass = card.owned ? "catalog-card owned" : "catalog-card";
  const priceText = formatCatalogPrice(card);
  const priceAttrs =
    card.price_nonfoil != null || card.price_foil != null
      ? `data-price-nonfoil="${escapeHtml(card.price_nonfoil != null ? money(card.price_nonfoil) : "")}" data-price-foil="${escapeHtml(card.price_foil != null ? money(card.price_foil) : "")}"`
      : "";
  const image = card.image_url
    ? `<img src="${card.image_url}" alt="${escapeHtml(card.name)}" loading="lazy" />`
    : `<div class="catalog-card-placeholder"></div>`;
  const openAttrs = card.scryfall_id
    ? `data-card-open data-card-id="${escapeHtml(card.scryfall_id)}" data-finish="${escapeHtml(card.finish || "nonfoil")}" role="button" tabindex="0"`
    : "";
  const footerClass = card.scryfall_id ? "catalog-card-footer" : "catalog-card-footer catalog-card-footer-no-actions";
  const minusBtn = card.scryfall_id
    ? `<button class="catalog-card-qty-btn" type="button" data-qty-delta="-1" aria-label="Retirer une copie">−</button>`
    : "";
  const plusBtn = card.scryfall_id
    ? `<button class="catalog-card-qty-btn" type="button" data-qty-delta="1" aria-label="Ajouter une copie">+</button>`
    : "";
  return `
    <article class="${ownedClass}" ${openAttrs} data-card-id="${escapeHtml(card.scryfall_id || "")}" data-finish="${escapeHtml(card.finish || "nonfoil")}">
      <div class="catalog-card-image-wrap">
        <div class="catalog-card-image">${image}</div>
        ${card.quantity ? `<span class="catalog-card-qty">${card.quantity}</span>` : ""}
      </div>
      <div class="${footerClass}">
        ${minusBtn}
        <span class="catalog-card-price" ${priceAttrs} title="${escapeHtml(priceText)}">${priceText}</span>
        ${plusBtn}
      </div>
    </article>
  `;
}

function backCollectionLevel() {
  if (state.collectionBrowse.level === "cards") {
    openCollectionSet(state.collectionBrowse.setCode, state.collectionBrowse.setName).catch((error) => toast(error.message));
    return;
  }
  if (state.collectionBrowse.level === "set") {
    showCollectionLevel("blocks").catch((error) => toast(error.message));
  }
}

function renderCollectionItem(item) {
  const card = item.card;
  return `
    <article class="collection-card openable-card" data-card-open data-card-id="${card.id}" data-finish="${item.finish}" role="button" tabindex="0">
      ${cardImage(card)}
      <div class="card-body">
        <h3 class="card-title">${escapeHtml(card.printed_name || card.name)}</h3>
        <div class="meta">${escapeHtml(card.set_name || card.set || "")} - ${escapeHtml(item.finish)} - x${item.quantity}</div>
        ${priceLabel(card.price)}
        <div class="meta">Ligne: ${money(item.estimated_line_value || 0)}</div>
        <div class="actions">
          <button class="secondary" data-detail data-card-id="${card.id}" data-finish="${item.finish}">Fiche</button>
          <button class="danger" data-delete data-item-id="${item.id}">Supprimer</button>
        </div>
      </div>
    </article>
  `;
}

async function deleteItem(itemId, button) {
  try {
    setLoading(button, true, "...");
    const collection = await api(`/api/collection/${itemId}`, { method: "DELETE" });
    state.collection = collection;
    renderCollection(collection);
    toast("Carte retiree");
  } catch (error) {
    toast(error.message);
  }
}

function bindCardOpen(root) {
  root.querySelectorAll("[data-card-open]").forEach((card) => {
    const open = () => showCardDetail(card.dataset.cardId, card.dataset.finish || "nonfoil");
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) {
        return;
      }
      open();
    });
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        open();
      }
    });
  });
}

function bindDetailButtons(root) {
  root.querySelectorAll("[data-detail]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      showCardDetail(button.dataset.cardId, button.dataset.finish || "nonfoil");
    });
  });
}

async function showCardDetail(cardId, finish) {
  try {
    openCardScreen();
    $("#priceDetails").innerHTML = `<p class="muted">Chargement de la fiche...</p>`;
    const payload = await api(`/api/cards/${cardId}/detail?finish=${encodeURIComponent(finish)}`);
    renderCardDetail(payload);
  } catch (error) {
    $("#priceDetails").innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
  }
}

function renderCardDetail(payload) {
  const card = payload.card;
  const details = payload.details || {};
  const history = payload.history || [];
  const periods = payload.periods || [];
  const rulings = payload.rulings || [];
  const markets = payload.markets || [];
  const mtgjson = payload.mtgjson || {};
  $("#priceDetails").innerHTML = `
    <section class="detail-hero">
      ${detailImage(card)}
      <div>
        <h3>${escapeHtml(card.printed_name || card.name)}</h3>
        <div class="meta">${escapeHtml(card.set_name || card.set || "")} #${escapeHtml(card.collector_number || "")}</div>
        <div class="meta">${escapeHtml(details.type_line || details.printed_type_line || "")}</div>
        ${priceLabel(card.price)}
      </div>
    </section>
    <div class="notice">
      L'historique combine les snapshots locaux et, quand disponible, MTGJSON AllPrices. Si aucune donnee plus ancienne n'existe pour une periode, la premiere date disponible est utilisee.
    </div>
    ${renderPeriodGrid(periods)}
    ${renderChart(history)}
    ${renderMtgjsonStatus(mtgjson)}
    ${renderMarkets(markets)}
    ${renderCardText(details)}
    ${renderRulings(rulings)}
    <div class="history-list">
      <h3>Snapshots prix</h3>
      ${
        history.length
          ? history
              .slice()
              .reverse()
              .map(
                (point) =>
                  `<div class="history-row"><span>${escapeHtml(point.snapshot_date)}</span><strong>${money(point.price)}</strong></div>`,
              )
              .join("")
          : `<p class="muted">Pas encore assez de snapshots pour tracer une evolution.</p>`
      }
    </div>
  `;
}

function renderMtgjsonStatus(mtgjson) {
  if (!mtgjson || !mtgjson.enabled) {
    return "";
  }
  const message = mtgjson.available
    ? `MTGJSON: ${mtgjson.points || 0} point(s) de prix trouves${mtgjson.cache_hit ? " depuis le cache" : ""}.`
    : `MTGJSON: ${mtgjson.message || "donnees indisponibles"}`;
  return `<p class="helper-text">${escapeHtml(message)}</p>`;
}

function renderMarkets(markets) {
  if (!markets.length) {
    return "";
  }
  return `
    <section class="detail-section">
      <h3>Sources de prix MTGJSON</h3>
      <div class="market-grid">
        ${markets
          .map(
            (market) => `
              <article>
                <span>${escapeHtml(market.source.replace("mtgjson-", ""))} - ${escapeHtml(market.currency)}</span>
                <strong>${formatMarketPrice(market)}</strong>
                <small>${escapeHtml(market.first_date)} -> ${escapeHtml(market.latest_date)} (${market.point_count} points)</small>
              </article>
            `,
          )
          .join("")}
      </div>
    </section>
  `;
}

function formatMarketPrice(market) {
  if (market.currency === "EUR") {
    return money(market.latest_price);
  }
  return `${Number(market.latest_price).toFixed(2)} ${escapeHtml(market.currency || "")}`;
}

function renderPeriodGrid(periods) {
  if (!periods.length) {
    return "";
  }
  return `
    <div class="period-grid">
      ${periods
        .map((period) => {
          if (!period.available) {
            return `<article><span>${escapeHtml(period.label)}</span><strong>N/A</strong><small>${escapeHtml(period.message)}</small></article>`;
          }
          const positive = Number(period.absolute_change || 0) >= 0;
          return `
            <article>
              <span>${escapeHtml(period.label)}</span>
              <strong class="${positive ? "positive" : "negative"}">${formatChange(period)}</strong>
              <small>${period.uses_first_available ? "depuis " : "depuis "}${escapeHtml(period.start_date)} -> ${escapeHtml(period.end_date)}</small>
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function formatChange(period) {
  const absolute = period.absolute_change || 0;
  const percent = period.percent_change;
  const sign = Number(absolute) > 0 ? "+" : "";
  const percentText = percent === null || percent === undefined ? "" : ` (${sign}${Number(percent).toFixed(1)}%)`;
  return `${sign}${money(absolute)}${percentText}`;
}

function renderCardText(details) {
  const faces = details.card_faces || [];
  const facesHtml = faces.length
    ? faces
        .map(
          (face) => `
            <article class="text-box">
              <h4>${escapeHtml(face.printed_name || face.name || "")} ${escapeHtml(face.mana_cost || "")}</h4>
              <p class="meta">${escapeHtml(face.printed_type_line || face.type_line || "")}</p>
              ${textBlock(face.printed_text || face.oracle_text)}
              ${textBlock(face.flavor_text, "flavor")}
            </article>
          `,
        )
        .join("")
    : "";

  return `
    <section class="detail-section">
      <h3>Details Scryfall</h3>
      <div class="detail-kv">
        <span>Cout</span><strong>${escapeHtml(details.mana_cost || "-")}</strong>
        <span>Mana value</span><strong>${details.cmc ?? "-"}</strong>
        <span>Artiste</span><strong>${escapeHtml(details.artist || "-")}</strong>
        <span>Sortie</span><strong>${escapeHtml(details.released_at || "-")}</strong>
      </div>
      ${textBlock(details.printed_text || details.oracle_text)}
      ${textBlock(details.flavor_text, "flavor")}
      ${facesHtml}
      ${renderKeywords(details.keywords || [])}
      ${renderLegalities(details.legalities || {})}
    </section>
  `;
}

function textBlock(text, className = "") {
  if (!text) {
    return "";
  }
  return `<p class="oracle-text ${className}">${escapeHtml(text).replaceAll("\n", "<br />")}</p>`;
}

function renderKeywords(keywords) {
  if (!keywords.length) {
    return "";
  }
  return `<div class="chips">${keywords.map((keyword) => `<span>${escapeHtml(keyword)}</span>`).join("")}</div>`;
}

function renderLegalities(legalities) {
  const visible = Object.entries(legalities).filter(([, value]) => value && value !== "not_legal");
  if (!visible.length) {
    return "";
  }
  return `
    <div class="legalities">
      ${visible.map(([format, value]) => `<span>${escapeHtml(format)}: ${escapeHtml(value)}</span>`).join("")}
    </div>
  `;
}

function renderRulings(rulings) {
  return `
    <section class="detail-section">
      <h3>Explications / rulings</h3>
      ${
        rulings.length
          ? rulings
              .slice(0, 8)
              .map(
                (ruling) => `
                  <article class="ruling">
                    <div class="meta">${escapeHtml(ruling.published_at || "")} - ${escapeHtml(ruling.source || "")}</div>
                    <p>${escapeHtml(ruling.comment || "")}</p>
                  </article>
                `,
              )
              .join("")
          : `<p class="muted">Aucun ruling specifique trouve sur Scryfall pour cette impression.</p>`
      }
    </section>
  `;
}

function renderChart(history) {
  if (!history.length) {
    return `<div class="chart"></div>`;
  }
  const width = 340;
  const height = 170;
  const padding = 20;
  const values = history.map((point) => Number(point.price));
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const points = history.map((point, index) => {
    const x = padding + (index * (width - padding * 2)) / Math.max(1, history.length - 1);
    const y = height - padding - ((Number(point.price) - min) * (height - padding * 2)) / spread;
    return `${x},${y}`;
  });
  const last = history[history.length - 1];
  return `
    <svg class="chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Courbe des prix">
      <polyline points="${points.join(" ")}" fill="none" stroke="#54d6a7" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
      ${points
        .map((point) => {
          const [x, y] = point.split(",");
          return `<circle cx="${x}" cy="${y}" r="4" fill="#a67cff" />`;
        })
        .join("")}
      <text x="${padding}" y="18" fill="#b8adc9" font-size="12">${money(max)}</text>
      <text x="${padding}" y="${height - 6}" fill="#b8adc9" font-size="12">${money(min)}</text>
      <text x="${width - padding}" y="${height - 6}" text-anchor="end" fill="#f7f3ff" font-size="12">${escapeHtml(
        last.snapshot_date,
      )}</text>
    </svg>
  `;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function refreshPrices(button) {
  try {
    setLoading(button, true, "Rafraichissement...");
    const collection = await api("/api/snapshots/refresh", {
      method: "POST",
      body: JSON.stringify({ collection_only: true }),
    });
    state.collection = collection;
    renderCollection(collection);
    toast(`${collection.refresh.cards_refreshed} carte(s) rafraichie(s)`);
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(button, false);
  }
}

$("#searchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button[type='submit']");
  const params = new URLSearchParams({
    q: $("#searchInput").value,
    lang: $("#langInput").value,
    finish: $("#finishInput").value,
    serialized: $("#serializedInput").checked ? "true" : "false",
  });
  try {
    setLoading(submit, true, "Recherche...");
    const payload = await api(`/api/search?${params.toString()}`);
    renderSearchResults(payload.cards);
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(submit, false);
  }
});

async function reloadDeckFilters() {
  await loadDeckExtensions();
  await loadDecks(1);
}

$("#deckSearchInput").addEventListener("input", scheduleDeckReload);
$("#commanderOnlyInput").addEventListener("change", () => reloadDeckFilters().catch((error) => toast(error.message)));
$("#hideCollectorInput").addEventListener("change", () => reloadDeckFilters().catch((error) => toast(error.message)));
$("#deckExtensionInput").addEventListener("change", () => loadDecks(1).catch((error) => toast(error.message)));
$("#deckSortInput").addEventListener("change", () => loadDecks(1).catch((error) => toast(error.message)));
$("#deckFilterToggle").addEventListener("click", (event) => toggleDeckPanel(event.currentTarget, $("#deckFilters")));
$("#deckMenuToggle").addEventListener("click", (event) => toggleDeckPanel(event.currentTarget, $("#deckMenu")));
$("#deckImportInfo").addEventListener("click", (event) => {
  const button = event.currentTarget;
  toast(button.getAttribute("title") || "Info import MTGJSON");
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});

$("#collectionBack").addEventListener("click", backCollectionLevel);
$("#preloadCommanderPrices").addEventListener("click", (event) => startCommanderPreload(event.currentTarget));
$("#backFromCard").addEventListener("click", backFromCard);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

loadCollection().catch((error) => toast(error.message));
initCatalogCardSize();
pollPreloadStatus();
