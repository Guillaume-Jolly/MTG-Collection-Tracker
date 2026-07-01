const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

const DECKS_PAGE_SIZE = 20;
const OWNED_DECKS_STORAGE_KEY = "mtg_owned_deck_files";

const CHART_RANGE_STORAGE_KEY = "mtg_default_chart_range";
const CHART_RANGE_DAYS = {
  "7d": 7,
  "1m": 30,
  "6m": 183,
  "1y": 365,
  "5y": 1825,
};
const CHART_MAX_POINTS = 20;
const CHART_VIEW_WIDTH = 500;
const CHART_VIEW_HEIGHT = 252;
const CHART_PAD = { top: 18, right: 14, bottom: 72, left: 58 };
const CHART_MIN_DATE_LABEL_GAP = 42;
const CHART_RANGE_OPTIONS = [
  { key: "7d", label: "7 jours" },
  { key: "1m", label: "1 mois" },
  { key: "6m", label: "6 mois" },
  { key: "1y", label: "1 an" },
  { key: "5y", label: "5 ans" },
];
const CHART_SOURCE_STORAGE_KEY = "mtg_default_chart_source";
const CHART_PREFS_VERSION_KEY = "mtg_chart_prefs_version";
const CHART_PREFS_VERSION = "cardmarket-guide-v1";
const CHART_HISTORY_OPTIONS_COLLECTION_KEY = "mtg_chart_history_opts_collection";
const CHART_HISTORY_OPTIONS_DECK_KEY = "mtg_chart_history_opts_deck";
const CHART_HISTORY_OPTIONS_MARKET_KEY = "mtg_chart_history_opts_market";
const DISPLAY_LANG_STORAGE_KEY = "mtg_display_lang";
const LEGACY_HISTORY_LANG_STORAGE_KEY = "mtg_card_history_lang";
const DISPLAY_LANG_OPTIONS = [
  { key: "fr", label: "FR" },
  { key: "en", label: "EN" },
  { key: "merge", label: "FR puis EN" },
];
const STARTUP_SPLASH_IMAGES = ["/splash/splash-1.png", "/splash/splash-2.png", "/splash/splash-3.png"];
const STARTUP_SPLASH_MIN_MS = 2400;
const DEFAULT_CHART_SOURCE = "cardmarket";
const DEFAULT_CHART_RANGE = "7d";
const CHART_SOURCE_OPTIONS = [
  { key: "cardmarket", label: "Cardmarket", currency: "EUR", dbSource: "cardmarket-guide" },
  { key: "cardkingdom", label: "Card Kingdom", currency: "USD", dbSource: "mtgjson-cardkingdom" },
  { key: "manapool", label: "ManaPool", currency: "USD", dbSource: "mtgjson-manapool" },
  { key: "tcgplayer", label: "TCGPlayer", currency: "USD", dbSource: "mtgjson-tcgplayer" },
];
const usd = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "USD" });

function applyDefaultChartPreferences() {
  const version = localStorage.getItem(CHART_PREFS_VERSION_KEY);
  if (version === CHART_PREFS_VERSION) {
    return;
  }
  localStorage.setItem(CHART_SOURCE_STORAGE_KEY, DEFAULT_CHART_SOURCE);
  localStorage.setItem(CHART_RANGE_STORAGE_KEY, DEFAULT_CHART_RANGE);
  localStorage.setItem(CHART_PREFS_VERSION_KEY, CHART_PREFS_VERSION);
}

function readChartSource() {
  const stored = localStorage.getItem(CHART_SOURCE_STORAGE_KEY);
  if (stored && CHART_SOURCE_OPTIONS.some((option) => option.key === stored)) {
    return stored;
  }
  return DEFAULT_CHART_SOURCE;
}

function saveChartSource(source) {
  if (!CHART_SOURCE_OPTIONS.some((option) => option.key === source)) {
    return;
  }
  localStorage.setItem(CHART_SOURCE_STORAGE_KEY, source);
  state.myCollection.chartSource = source;
  if (state.cardDetail) {
    state.cardDetail.source = source;
  }
}

function chartSourceMeta(sourceKey) {
  return CHART_SOURCE_OPTIONS.find((option) => option.key === sourceKey) || CHART_SOURCE_OPTIONS[0];
}

function mergeCardmarketHistory(history) {
  const byDate = new Map();
  const sourceRank = { "scryfall-cardmarket": 0, "cardmarket-guide": 1, "mtgjson-cardmarket": 2 };
  for (const point of history || []) {
    if (!["scryfall-cardmarket", "cardmarket-guide", "mtgjson-cardmarket"].includes(point.source)) {
      continue;
    }
    const existing = byDate.get(point.snapshot_date);
    if (!existing) {
      byDate.set(point.snapshot_date, point);
      continue;
    }
    const leftRank = sourceRank[existing.source] ?? 99;
    const rightRank = sourceRank[point.source] ?? 99;
    if (rightRank < leftRank) {
      byDate.set(point.snapshot_date, point);
    }
  }
  return [...byDate.values()].sort((left, right) => left.snapshot_date.localeCompare(right.snapshot_date));
}

function filterHistoryBySource(history, sourceKey) {
  if (sourceKey === "cardmarket") {
    return mergeCardmarketHistory(history);
  }
  const meta = chartSourceMeta(sourceKey);
  return (history || []).filter((point) => point.source === meta.dbSource);
}

function formatChartMoney(value, currency = "EUR") {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return "—";
  }
  if (currency === "USD") {
    return usd.format(amount);
  }
  return money(amount);
}

function finishLabel(finish) {
  return (
    {
      nonfoil: "Non-foil",
      foil: "Foil",
      etched: "Etched",
    }[finish] || finish
  );
}

function cardAvailableFinishes(card) {
  const valid = ["nonfoil", "foil", "etched"];
  const seen = new Set();
  const finishes = [];
  for (const finish of [...(card?.available_finishes || []), ...(card?.finishes || [])]) {
    if (!valid.includes(finish) || seen.has(finish)) {
      continue;
    }
    seen.add(finish);
    finishes.push(finish);
  }
  if (finishes.length) {
    return finishes;
  }
  return [card?.display_finish || "nonfoil"];
}

function finishPriceLabel(card, finish) {
  const price = card?.prices_by_finish?.[finish] || (card?.display_finish === finish ? card?.price : null);
  if (!price || price.price == null) {
    return "";
  }
  return `<span class="detail-finish-price">${money(price.price)}</span>`;
}

function renderChartSourceGrid(selectedKey) {
  const tiles = CHART_SOURCE_OPTIONS.map(
    (option) => `
      <button
        type="button"
        class="chart-option-tile chart-source-tile ${selectedKey === option.key ? "is-active" : ""}"
        data-chart-source="${option.key}"
        aria-pressed="${selectedKey === option.key ? "true" : "false"}"
      >
        <span>${escapeHtml(option.label)}</span>
        <small>${escapeHtml(option.currency)}</small>
      </button>
    `,
  );
  return `<div class="chart-option-grid" role="group" aria-label="Source des prix">${tiles.join("")}</div>`;
}

function renderChartSourceColumn(selectedKey, interactive = true) {
  if (interactive) {
    return renderChartSourceGrid(selectedKey);
  }
  return `
    <div class="chart-option-grid" role="group" aria-label="Source des prix">
      <button type="button" class="chart-option-tile chart-source-tile is-active" disabled aria-pressed="true">
        <span>Cardmarket</span>
        <small>EUR</small>
      </button>
    </div>
  `;
}

function bindChartSourceTiles(root, onSourceChange) {
  if (!root || !onSourceChange) {
    return;
  }
  root.querySelectorAll("[data-chart-source]").forEach((tile) => {
    const activate = () => {
      if (tile.disabled) {
        return;
      }
      root.querySelectorAll("[data-chart-source]").forEach((node) => {
        const active = node === tile;
        node.classList.toggle("is-active", active);
        node.setAttribute("aria-pressed", active ? "true" : "false");
      });
      onSourceChange(tile.dataset.chartSource);
    };
    tile.addEventListener("click", activate);
  });
}

function defaultChartHistoryOptions() {
  return {
    onlyPriced: false,
    excludeAddedAfter: "",
    excludeNewCards: false,
    excludeMoversCommon: false,
    excludeMoversUncommon: false,
    excludeMoversRare: false,
    excludeMoversSpecial: false,
    priceMode: "owned",
    excludeIlliquid: false,
    speculativePreset: "",
    marketMetric: "trend",
  };
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

let startupSplashImageTimer = null;
let startupSplashImageIndex = 0;

function rotateStartupSplashImage() {
  const image = document.getElementById("startupSplashImage");
  if (!image || !STARTUP_SPLASH_IMAGES.length) {
    return;
  }
  startupSplashImageIndex = (startupSplashImageIndex + 1) % STARTUP_SPLASH_IMAGES.length;
  image.style.opacity = "0";
  window.setTimeout(() => {
    image.src = STARTUP_SPLASH_IMAGES[startupSplashImageIndex];
    image.style.opacity = "0.72";
  }, 280);
}

function showStartupSplash() {
  const overlay = document.getElementById("startupSplash");
  if (!overlay) {
    return;
  }
  const versionNode = document.getElementById("startupSplashVersion");
  if (versionNode && window.MTG_APP_VERSION) {
    versionNode.textContent = window.MTG_APP_VERSION;
  }
  startupSplashImageIndex = 0;
  const image = document.getElementById("startupSplashImage");
  if (image) {
    image.src = STARTUP_SPLASH_IMAGES[0];
    image.style.opacity = "0.72";
  }
  document.body.classList.add("startup-loading");
  overlay.classList.remove("hidden");
  if (startupSplashImageTimer) {
    window.clearInterval(startupSplashImageTimer);
  }
  startupSplashImageTimer = window.setInterval(rotateStartupSplashImage, 3200);
}

function hideStartupSplash() {
  const overlay = document.getElementById("startupSplash");
  if (startupSplashImageTimer) {
    window.clearInterval(startupSplashImageTimer);
    startupSplashImageTimer = null;
  }
  document.body.classList.remove("startup-loading");
  overlay?.classList.add("hidden");
}

function renderStartupSplashStatus(status) {
  const message = document.getElementById("startupSplashMessage");
  const bar = document.getElementById("startupSplashProgressBar");
  const percent = document.getElementById("startupSplashPercent");
  const title = document.getElementById("startupSplashTitle");
  const phase = status.phase || "";
  const defaultMessage =
    phase === "owned_prices" || phase === "market"
      ? "Prix en cours de chargement..."
      : "Chargement...";
  if (message) {
    message.textContent = status.message || defaultMessage;
  }
  if (title) {
    const loadingPhases = new Set(["owned_prices", "market", "catalog", "siblings", "decks", "starting"]);
    title.textContent = loadingPhases.has(phase) ? "Preparation de l'arene..." : "Bienvenue";
  }
  const value = Math.max(0, Math.min(100, Number(status.progress) || 0));
  if (bar) {
    bar.style.width = `${value}%`;
  }
  if (percent) {
    percent.textContent = `${value}%`;
  }
}

async function waitForStartupWarmup() {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const status = await api("/api/startup/status");
    renderStartupSplashStatus(status);
    if (!status.running) {
      return status;
    }
    await sleep(500);
  }
  return { running: false, progress: 100, message: "Chargement termine" };
}

function startupSplashErrorMessage(error) {
  const message = String(error?.message || error || "");
  if (message === "Not found" || message.includes("404")) {
    return "Serveur a mettre a jour — redemarrez run_mvp.py ou launch.bat";
  }
  return message || "Chargement...";
}

async function runStartupSplash() {
  if (new URLSearchParams(window.location.search).has("nosplash")) {
    return;
  }
  showStartupSplash();
  const startedAt = Date.now();
  try {
    await api("/api/startup/warmup", { method: "POST", body: JSON.stringify({}) });
    await waitForStartupWarmup();
  } catch (error) {
    renderStartupSplashStatus({
      message: startupSplashErrorMessage(error),
      progress: 100,
    });
  }
  const elapsed = Date.now() - startedAt;
  if (elapsed < STARTUP_SPLASH_MIN_MS) {
    await sleep(STARTUP_SPLASH_MIN_MS - elapsed);
  }
  hideStartupSplash();
}

function readDisplayLang() {
  const stored = localStorage.getItem(DISPLAY_LANG_STORAGE_KEY);
  if (stored && DISPLAY_LANG_OPTIONS.some((option) => option.key === stored)) {
    return stored;
  }
  const legacy = localStorage.getItem(LEGACY_HISTORY_LANG_STORAGE_KEY);
  if (legacy === "both") {
    return "merge";
  }
  if (legacy && DISPLAY_LANG_OPTIONS.some((option) => option.key === legacy)) {
    return legacy;
  }
  return "merge";
}

function saveDisplayLang(mode) {
  if (!DISPLAY_LANG_OPTIONS.some((option) => option.key === mode)) {
    return;
  }
  localStorage.setItem(DISPLAY_LANG_STORAGE_KEY, mode);
  state.displayLang = mode;
}

function displayLangLabel(mode) {
  return DISPLAY_LANG_OPTIONS.find((option) => option.key === mode)?.label || mode;
}

function withDisplayLang(params) {
  const next = params instanceof URLSearchParams ? new URLSearchParams(params) : new URLSearchParams(params || {});
  next.set("display_lang", readDisplayLang());
  return next;
}

function syncGlobalDisplayLangUi(mode = readDisplayLang()) {
  document.querySelectorAll("#globalDisplayLang [data-display-lang]").forEach((button) => {
    const active = button.dataset.displayLang === mode;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function bindGlobalDisplayLangControl() {
  const host = document.getElementById("globalDisplayLang");
  if (!host || host.dataset.bound === "true") {
    return;
  }
  host.dataset.bound = "true";
  host.addEventListener("click", (event) => {
    const button = event.target.closest("[data-display-lang]");
    if (!button) {
      return;
    }
    const nextLang = button.dataset.displayLang;
    if (!nextLang || nextLang === readDisplayLang()) {
      return;
    }
    saveDisplayLang(nextLang);
    syncGlobalDisplayLangUi(nextLang);
    applyDisplayLangChange().catch((error) => toast(error.message));
  });
}

async function applyDisplayLangChange() {
  if (state.currentTab === "search" && $("#searchInput")?.value.trim()) {
    $("#searchForm").requestSubmit();
    return;
  }
  if (state.currentTab === "my-collection") {
    await loadMyCollection();
    return;
  }
  if (state.currentTab === "collection" && state.collectionBrowse?.sectionCode) {
    await loadCollectionCards();
    return;
  }
  if (state.currentTab === "market") {
    await loadMarket();
    return;
  }
  if (state.currentTab === "prices" && state.cardDetail?.cardId) {
    const finish = state.cardDetail.selectedFinish || state.cardDetail.finish || "nonfoil";
    const payload = await api(
      `/api/cards/${state.cardDetail.cardId}/detail?finish=${encodeURIComponent(finish)}&${withDisplayLang().toString()}`,
    );
    renderCardDetail(payload);
  }
}

function historyLangHint(historyLang) {
  if (historyLang === "merge") {
    return "Affichage fusion : version FR en priorite, sinon EN (image, prix et historique).";
  }
  if (historyLang === "fr") {
    return "Affichage en francais uniquement (image, prix et historique).";
  }
  return "Affichage en anglais uniquement (image, prix et historique).";
}

function historyPointLangBadge(point, historyLang) {
  if ((historyLang !== "merge" && historyLang !== "both") || !point.price_lang) {
    return "";
  }
  const label = point.price_lang === "fr" ? "FR" : "EN";
  return `<span class="history-row-lang muted">${escapeHtml(label)}</span>`;
}

function renderHistoryRows(points, currency, historyLang) {
  if (!points.length) {
    return `<p class="muted">Pas encore de snapshots pour cette periode.</p>`;
  }
  return points
    .slice()
    .reverse()
    .map(
      (point) =>
        `<div class="history-row"><span>${escapeHtml(point.snapshot_date)}</span>${historyPointLangBadge(point, historyLang)}<strong>${formatChartMoney(point.price, currency)}</strong></div>`,
    )
    .join("");
}

function chartHistoryOptionsKey(scope = "collection") {
  if (scope === "deck") {
    return CHART_HISTORY_OPTIONS_DECK_KEY;
  }
  if (scope === "market") {
    return CHART_HISTORY_OPTIONS_MARKET_KEY;
  }
  return CHART_HISTORY_OPTIONS_COLLECTION_KEY;
}

function readChartHistoryOptions(scope = "collection") {
  const key = chartHistoryOptionsKey(scope);
  try {
    const stored = JSON.parse(localStorage.getItem(key) || "{}");
    return { ...defaultChartHistoryOptions(), ...stored };
  } catch {
    return defaultChartHistoryOptions();
  }
}

function saveChartHistoryOptions(scope, options) {
  localStorage.setItem(chartHistoryOptionsKey(scope), JSON.stringify(options));
}

function readHistoryOptionsFromRoot(root, scope = "collection") {
  const stored = readChartHistoryOptions(scope);
  if (!root) {
    return stored;
  }
  const chartHost = root.querySelector("[data-chart-options-host]");
  const moversHost = root.querySelector("[data-movers-options-host]");
  const marketHost = root.querySelector("[data-market-filter-host]");
  return {
    ...stored,
    onlyPriced: chartHost?.querySelector("[data-chart-only-priced]")?.checked ?? stored.onlyPriced,
    excludeAddedAfter: chartHost?.querySelector("[data-chart-exclude-after]")?.value ?? stored.excludeAddedAfter ?? "",
    excludeNewCards: chartHost?.querySelector("[data-chart-exclude-new]")?.checked ?? stored.excludeNewCards,
    priceMode: chartHost?.querySelector("[data-chart-price-mode]")?.value ?? stored.priceMode ?? "owned",
    excludeMoversCommon: moversHost?.querySelector("[data-movers-exclude-common]")?.checked ?? stored.excludeMoversCommon,
    excludeMoversUncommon: moversHost?.querySelector("[data-movers-exclude-uncommon]")?.checked ?? stored.excludeMoversUncommon,
    excludeMoversRare: moversHost?.querySelector("[data-movers-exclude-rare]")?.checked ?? stored.excludeMoversRare,
    excludeMoversSpecial: moversHost?.querySelector("[data-movers-exclude-special]")?.checked ?? stored.excludeMoversSpecial,
    excludeIlliquid: marketHost?.querySelector("[data-market-exclude-illiquid]")?.checked ?? stored.excludeIlliquid,
    speculativePreset: marketHost?.querySelector("[data-market-preset]")?.value ?? stored.speculativePreset ?? "",
    marketMetric: marketHost?.querySelector("[data-market-metric]")?.value ?? stored.marketMetric ?? "trend",
  };
}

function buildHistoryQueryParams(source, options = {}, range = null) {
  const params = new URLSearchParams({ source: source || DEFAULT_CHART_SOURCE });
  if (range) {
    params.set("range", range);
  }
  if (options.onlyPriced) {
    params.set("only_priced", "1");
  }
  if (options.excludeAddedAfter) {
    params.set("exclude_added_after", options.excludeAddedAfter);
  }
  if (options.excludeNewCards) {
    params.set("exclude_new_cards", "1");
  }
  if (options.excludeMoversCommon) {
    params.set("exclude_movers_common", "1");
  }
  if (options.excludeMoversUncommon) {
    params.set("exclude_movers_uncommon", "1");
  }
  if (options.excludeMoversRare) {
    params.set("exclude_movers_rare", "1");
  }
  if (options.excludeMoversSpecial) {
    params.set("exclude_movers_special", "1");
  }
  if (options.priceMode && options.priceMode !== "owned") {
    params.set("price_mode", options.priceMode);
  }
  if (options.excludeIlliquid) {
    params.set("exclude_illiquid", "1");
  }
  if (options.speculativePreset) {
    params.set("speculative_preset", options.speculativePreset);
  }
  if (options.marketMetric && options.marketMetric !== "trend") {
    params.set("market_metric", options.marketMetric);
  }
  return params.toString();
}

function renderMoversOptionsColumn(options) {
  return `
    <div data-movers-options-host>
      <div class="collection-movers-options" role="group" aria-label="Filtres de rarete pour les variations">
        <label class="collection-movers-option">
          <input type="checkbox" data-movers-exclude-common ${options.excludeMoversCommon ? "checked" : ""} />
          <span>Ignorer communes</span>
        </label>
        <label class="collection-movers-option">
          <input type="checkbox" data-movers-exclude-uncommon ${options.excludeMoversUncommon ? "checked" : ""} />
          <span>Ignorer uncos</span>
        </label>
        <label class="collection-movers-option">
          <input type="checkbox" data-movers-exclude-rare ${options.excludeMoversRare ? "checked" : ""} />
          <span>Ignorer rares</span>
        </label>
        <label class="collection-movers-option">
          <input type="checkbox" data-movers-exclude-special ${options.excludeMoversSpecial ? "checked" : ""} />
          <span>Ignorer versions speciales</span>
        </label>
      </div>
    </div>
  `;
}

function readMoversOptionsFromHost(host, scope = "collection") {
  return readHistoryOptionsFromRoot(host, scope);
}

function bindMoversOptions(moversHost, scope, onChange, panelRoot = null) {
  if (!moversHost) {
    return;
  }
  const root = panelRoot || moversHost.closest("[data-market-panel-root], #myCollectionHistoryChart") || moversHost;
  const apply = () => {
    const next = readHistoryOptionsFromRoot(root, scope);
    saveChartHistoryOptions(scope, next);
    onChange(next);
  };
  root.querySelectorAll("[data-movers-options-host] .collection-movers-options input[type='checkbox']").forEach((input) => {
    input.addEventListener("change", apply);
  });
  root.querySelectorAll("[data-market-filter-host] select, [data-market-filter-host] input[type='checkbox']").forEach((input) => {
    input.addEventListener("change", apply);
  });
}

function renderChartOptionsColumn(options, { showExcludeAdded = false } = {}) {
  return `
    <div class="chart-filter-grid">
      <label class="chart-filter check-row">
        <input type="checkbox" data-chart-only-priced ${options.onlyPriced ? "checked" : ""} />
        <span>Cartes avec prix uniquement</span>
      </label>
      ${
        showExcludeAdded
          ? `
        <label class="chart-filter">
          <span>Ignorer ajouts apres</span>
          <input type="date" data-chart-exclude-after value="${escapeHtml(options.excludeAddedAfter || "")}" />
        </label>
        <label class="chart-filter check-row">
          <input type="checkbox" data-chart-exclude-new ${options.excludeNewCards ? "checked" : ""} />
          <span>Exclure les nouvelles cartes</span>
        </label>
      `
          : ""
      }
      <label class="chart-filter">
        <span>Finition du prix</span>
        <select data-chart-price-mode>
          <option value="owned" ${options.priceMode === "owned" ? "selected" : ""}>Finition possedee</option>
          <option value="nonfoil" ${options.priceMode === "nonfoil" ? "selected" : ""}>Prix non-foil</option>
        </select>
      </label>
    </div>
  `;
}

function bindChartHistoryOptions(root, scope, onChange, { showExcludeAdded = false } = {}) {
  const host = root.querySelector("[data-chart-options-host]");
  if (!host) {
    return;
  }
  const apply = () => {
    const next = readHistoryOptionsFromRoot(root, scope);
    saveChartHistoryOptions(scope, next);
    onChange(next);
  };
  host.querySelector("[data-chart-only-priced]")?.addEventListener("change", apply);
  host.querySelector("[data-chart-price-mode]")?.addEventListener("change", apply);
  if (showExcludeAdded) {
    host.querySelector("[data-chart-exclude-after]")?.addEventListener("change", apply);
    host.querySelector("[data-chart-exclude-new]")?.addEventListener("change", apply);
  }
}

function renderHistorySummary(valuation, chartOptions = {}) {
  const meta = valuation?.meta || {};
  const parts = [`${valuation?.priced_cards || 0} avec prix`];
  if (!chartOptions.onlyPriced && valuation?.missing_cards) {
    parts.push(`${valuation.missing_cards} sans prix`);
  }
  if (meta.snapshot_lines != null) {
    parts.push(`${meta.snapshot_lines} lignes historisees`);
  }
  if (meta.live_today_included) {
    parts.push("aujourd'hui via Scryfall");
  }
  if (meta.excluded_by_date) {
    parts.push(`${meta.excluded_by_date} excl. par date`);
  }
  if (meta.excluded_new_cards) {
    parts.push(`${meta.excluded_new_cards} nouv. excl.`);
  }
  const priceModeLabel = chartOptions.priceMode === "nonfoil" ? " · prix non-foil" : "";
  return `${parts.join(" · ")} · ${escapeHtml(valuation?.history_source || "Cardmarket")}${priceModeLabel}`;
}

function renderChartPanel({
  history,
  range,
  currency = "EUR",
  periods = [],
  sourceKey = null,
  sourceInteractive = true,
  summaryHtml = "",
  chartOptions = null,
  showExcludeAdded = false,
  historyLang = null,
}) {
  const optionsCol = chartOptions
    ? `
          <div class="chart-panel-col">
            <span class="chart-panel-col-label">Options</span>
            <div data-chart-options-host>${renderChartOptionsColumn(chartOptions, { showExcludeAdded })}</div>
          </div>
        `
    : "";
  return `
    <div class="chart-panel">
      ${summaryHtml ? `<div class="chart-panel-summary-wrap">${summaryHtml}</div>` : ""}
      <div class="chart-panel-body">
        <div class="chart-panel-options">
          <div class="chart-panel-col">
            <span class="chart-panel-col-label">Periode</span>
            <div data-period-grid-host>${renderChartPeriodColumn(periods, range, history, currency)}</div>
          </div>
          <div class="chart-panel-col">
            <span class="chart-panel-col-label">Source</span>
            <div data-chart-source-host>${renderChartSourceColumn(sourceKey, sourceInteractive)}</div>
          </div>
          ${optionsCol}
        </div>
        <div class="chart-panel-graph" data-chart-section>
          ${renderInteractiveChart(history, range, currency, historyLang)}
        </div>
      </div>
    </div>
  `;
}

function syncChartPanelHeights(root = document) {
  const stackOnMobile = window.matchMedia("(max-width: 719px)").matches;
  root.querySelectorAll(".chart-panel").forEach((panel) => {
    const options = panel.querySelector(".chart-panel-options");
    const graph = panel.querySelector(".chart-panel-graph");
    if (!options || !graph) {
      return;
    }
    if (stackOnMobile) {
      graph.style.maxHeight = "";
      graph.style.height = "";
      return;
    }
    const cap = options.offsetHeight;
    graph.style.maxHeight = `${cap + 28}px`;
    graph.style.height = `${cap + 28}px`;
  });
}

function bindPeriodTiles(root, onRangeChange) {
  root.querySelectorAll("[data-chart-range]").forEach((tile) => {
    const activate = () => {
      root.querySelectorAll("[data-chart-range]").forEach((node) => {
        const active = node === tile;
        node.classList.toggle("is-active", active);
        node.setAttribute("aria-pressed", active ? "true" : "false");
        node.setAttribute("aria-selected", active ? "true" : "false");
      });
      onRangeChange(tile.dataset.chartRange);
    };
    tile.addEventListener("click", activate);
    tile.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
  });
}

function readChartRange() {
  const stored = localStorage.getItem(CHART_RANGE_STORAGE_KEY);
  if (stored === "1d") {
    return DEFAULT_CHART_RANGE;
  }
  if (stored && CHART_RANGE_DAYS[stored]) {
    return stored;
  }
  return DEFAULT_CHART_RANGE;
}

function saveChartRange(range) {
  if (!CHART_RANGE_DAYS[range]) {
    return;
  }
  localStorage.setItem(CHART_RANGE_STORAGE_KEY, range);
  state.myCollection.chartRange = range;
  if (state.cardDetail) {
    state.cardDetail.range = range;
  }
}

applyDefaultChartPreferences();

const state = {
  collection: null,
  displayLang: readDisplayLang(),
  currentTab: "search",
  previousTab: "search",
  decks: {
    page: 1,
    total: 0,
    totalPages: 1,
    loading: false,
    searchTimer: null,
    requestedPage: 1,
    reloadAfterCurrent: false,
    cachedDecks: null,
  },
  collectionBrowse: {
    level: "blocks",
    setCode: null,
    setName: null,
    sectionCode: null,
    sectionLabel: null,
    pendingBlockFocus: null,
    sortPrimary: "price_desc",
    sortSecondary: "",
    multiSort: false,
    cardsTotal: 0,
    cardSize: 110,
    blockSetSort: "default",
    selectedCardIds: [],
    orderFinish: "nonfoil",
  },
  myCollection: {
    sortPrimary: "name_asc",
    sortSecondary: "",
    multiSort: false,
    cardSize: 110,
    chartRange: readChartRange(),
    chartSource: readChartSource(),
    chartOptions: readChartHistoryOptions("collection"),
    optionsOpen: false,
    history: null,
  },
  market: {
    chartRange: readChartRange(),
    chartSource: readChartSource(),
    chartOptions: readChartHistoryOptions("market"),
    payload: null,
    loading: false,
  },
  cardDetail: null,
};

let myCollectionHistoryRequestId = 0;

const $ = (selector) => document.querySelector(selector);

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
  } catch {
    throw new Error("Serveur inaccessible — lancez run_mvp.py (port 8000) ou launch.bat prod (port 8001), puis rechargez.");
  }
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Reponse serveur invalide (${response.status}). Redemarrez le serveur Python.`);
  }
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
  document.body.classList.toggle("my-collection-full-width", tab === "my-collection");
  document.body.classList.toggle("decks-full-width", tab === "decks");
  document.body.classList.toggle("market-full-width", tab === "market");
  applyDisplayZoom(readStoredDisplayZoom(), { persist: false });
  if (tab === "decks") {
    $("#deckPreview").innerHTML = "";
    loadDeckExtensions()
      .then(() =>
        loadDecks(state.decks.page, {
          silent: Boolean(state.decks.cachedDecks?.length),
        }),
      )
      .catch((error) => toast(error.message));
  }
  if (tab === "collection") {
    showCollectionLevel(state.collectionBrowse.level).catch((error) => toast(error.message));
  }
  if (tab === "my-collection") {
    loadMyCollection().catch((error) => toast(error.message));
  }
  if (tab === "market") {
    loadMarket().catch((error) => toast(error.message));
  }
}

function openCardScreen() {
  if (state.currentTab !== "prices") {
    state.previousTab = state.currentTab;
  }
  switchTab("prices");
}

function backFromCard() {
  state.cardDetailNav = null;
  switchTab(state.previousTab || "search");
}

function buildCardNavList(root) {
  const cards = [...root.querySelectorAll("[data-card-open]")].filter((el) => el.dataset.cardId);
  if (cards.length <= 1) {
    return null;
  }
  return cards.map((el) => ({
    cardId: el.dataset.cardId,
    finish: el.dataset.finish || "nonfoil",
  }));
}

function updateDetailNavControls() {
  const nav = state.cardDetailNav;
  const wrap = $("#cardDetailNav");
  const prev = $("#prevCard");
  const next = $("#nextCard");
  const label = $("#cardDetailNavLabel");
  const hasNav = Boolean(nav?.items?.length > 1);
  wrap?.classList.toggle("hidden", !hasNav);
  if (!hasNav || !nav) {
    return;
  }
  if (prev) {
    prev.disabled = nav.index <= 0;
  }
  if (next) {
    next.disabled = nav.index >= nav.items.length - 1;
  }
  if (label) {
    label.textContent = `${nav.index + 1} / ${nav.items.length}`;
  }
}

function navigateCardDetail(delta) {
  const nav = state.cardDetailNav;
  if (!nav?.items?.length) {
    return;
  }
  const nextIndex = nav.index + delta;
  if (nextIndex < 0 || nextIndex >= nav.items.length) {
    return;
  }
  nav.index = nextIndex;
  const item = nav.items[nextIndex];
  showCardDetail(item.cardId, item.finish, { fromNav: true }).catch((error) => toast(error.message));
}

function priceLabel(price) {
  if (!price) {
    return `<div class="price">Prix EUR indisponible</div>`;
  }
  let hint = "";
  if (price.is_fallback) {
    hint = `<span class="fallback">dernier prix trouve</span>`;
  } else if (String(price.source || "").includes("en-print")) {
    hint = `<span class="fallback">prix version EN</span>`;
  }
  return `<div class="price">${money(price.price)} <span class="meta">${escapeHtml(price.finish)}</span> ${hint}</div>`;
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
  applyCatalogCardSize(readStoredDisplayZoom(), { persist: false });
  bindCardOpen(node);
  node.querySelectorAll("[data-search-add]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      addCard(button.dataset.cardId, button.dataset.finish, button);
    });
  });
}

function renderSearchCard(card) {
  const finish = card.display_finish || card.price?.finish || "nonfoil";
  const image = card.image_url
    ? `<img src="${card.image_url}" alt="${escapeHtml(card.printed_name || card.name)}" loading="lazy" />`
    : `<div class="catalog-card-placeholder"></div>`;
  const priceHtml =
    card.price?.price != null
      ? `<span class="catalog-card-price">${money(card.price.price)}</span>`
      : `<span class="catalog-card-price muted">—</span>`;
  return `
    <article
      class="catalog-card openable-card"
      data-card-open
      data-card-id="${escapeHtml(card.id)}"
      data-finish="${escapeHtml(finish)}"
      role="button"
      tabindex="0"
      aria-label="${escapeHtml(card.printed_name || card.name)}"
    >
      <div class="catalog-card-image-wrap">
        <div class="catalog-card-image">${image}</div>
      </div>
      <div class="catalog-card-footer">
        <span class="catalog-card-footer-spacer" aria-hidden="true"></span>
        ${priceHtml}
        <button
          class="catalog-card-qty-btn"
          type="button"
          data-search-add
          data-card-id="${escapeHtml(card.id)}"
          data-finish="${escapeHtml(finish)}"
          aria-label="Ajouter a la collection"
        >+</button>
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
  applyDisplayZoom(readStoredDisplayZoom(), { persist: false });
  node.querySelectorAll("[data-preview-deck]").forEach((button) => {
    button.addEventListener("click", () => showDeckDetail(button.dataset.fileName, button));
  });
  node.querySelectorAll("[data-import-deck]").forEach((button) => {
    button.addEventListener("click", () => importDeck(button.dataset.fileName, button));
  });
  bindDeckOwnedToggles(node);
}

async function toggleDeckOwned(fileName, owned, checkbox) {
  try {
    const payload = await api("/api/decks/owned", {
      method: "POST",
      body: JSON.stringify({ file_name: fileName, owned }),
    });
    rememberOwnedDeck(fileName, payload.owned);
    applyDeckOwnedUi(fileName, payload.owned, payload);
    updateCachedDeckOwned(fileName, payload.owned, payload);
  } catch (error) {
    checkbox.checked = !owned;
    toast(error.message);
  }
}

function updateCachedDeckOwned(fileName, owned, meta = {}) {
  if (!state.decks.cachedDecks?.length || !fileName) {
    return;
  }
  state.decks.cachedDecks = state.decks.cachedDecks.map((deck) =>
    deck.file_name === fileName ? { ...deck, owned, ...meta } : deck,
  );
}

function applyDeckOwnedUi(fileName, owned, meta = {}) {
  if (!fileName) {
    return;
  }
  document.querySelectorAll(`[data-deck-file="${CSS.escape(fileName)}"]`).forEach((card) => {
    card.classList.toggle("is-owned", owned);
    const checkbox = card.querySelector("[data-toggle-deck-owned]");
    if (checkbox) {
      checkbox.checked = owned;
    }
    card.querySelectorAll("[data-import-deck]").forEach((button) => {
      const defaultLabel = button.dataset.importLabel || "Ajouter";
      button.disabled = owned;
      button.textContent = owned ? "Possede" : defaultLabel;
      delete button.dataset.previousLabel;
    });
    const progress = card.querySelector("[data-deck-collection-progress]");
    if (progress && meta.total_cards) {
      progress.textContent = `${meta.collected_cards || meta.total_cards}/${meta.total_cards}`;
    }
  });
}

function bindDeckOwnedToggles(root) {
  root.querySelectorAll("[data-toggle-deck-owned]").forEach((checkbox) => {
    checkbox.addEventListener("click", (event) => {
      event.stopPropagation();
    });
    checkbox.addEventListener("change", (event) => {
      const input = event.currentTarget;
      toggleDeckOwned(input.dataset.fileName, input.checked, input).catch((error) => toast(error.message));
    });
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

function readOwnedDeckFiles() {
  try {
    const raw = localStorage.getItem(OWNED_DECKS_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(parsed) ? parsed.filter(Boolean) : []);
  } catch {
    return new Set();
  }
}

function writeOwnedDeckFiles(files) {
  localStorage.setItem(OWNED_DECKS_STORAGE_KEY, JSON.stringify([...files]));
}

function rememberOwnedDeck(fileName, owned) {
  if (!fileName) {
    return;
  }
  const files = readOwnedDeckFiles();
  if (owned) {
    files.add(fileName);
  } else {
    files.delete(fileName);
  }
  writeOwnedDeckFiles(files);
}

function syncOwnedDecksFromApi(decks) {
  const files = readOwnedDeckFiles();
  let changed = false;
  for (const deck of decks) {
    if (!deck.file_name) {
      continue;
    }
    if (deck.owned) {
      if (!files.has(deck.file_name)) {
        files.add(deck.file_name);
        changed = true;
      }
    } else if (files.has(deck.file_name)) {
      files.delete(deck.file_name);
      changed = true;
    }
  }
  if (changed) {
    writeOwnedDeckFiles(files);
  }
}

function withLocalOwnedState(deck) {
  return deck;
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

async function loadDecks(page = 1, options = {}) {
  const { silent = false } = options;
  state.decks.requestedPage = page;

  if (state.decks.loading) {
    state.decks.reloadAfterCurrent = true;
    return;
  }

  state.decks.loading = true;
  state.decks.page = page;
  const node = $("#deckResults");
  if (!silent && state.decks.cachedDecks?.length) {
    renderDeckResults(state.decks.cachedDecks);
  } else if (!silent) {
    node.innerHTML = `<div class="panel"><p class="muted">Chargement des decks...</p></div>`;
  }

  try {
    const payload = await api(`/api/decks/search?${deckSearchParams(page).toString()}`);
    if (state.decks.requestedPage !== page) {
      return;
    }
    state.decks.total = payload.total || 0;
    state.decks.totalPages = payload.total_pages || 1;
    const decks = (payload.decks || []).map(withLocalOwnedState);
    syncOwnedDecksFromApi(decks);
    state.decks.cachedDecks = decks;
    renderDeckListMeta(payload);
    renderDeckResults(decks);
    renderDeckPagination(payload);
    if (page > 1) {
      $("#deckResults").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } finally {
    state.decks.loading = false;
    if (state.decks.reloadAfterCurrent) {
      state.decks.reloadAfterCurrent = false;
      const nextPage = state.decks.requestedPage;
      loadDecks(nextPage, options).catch((error) => toast(error.message));
    }
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

function renderDeckThumbnail(thumbnail) {
  if (!thumbnail?.image_url) {
    return `<div class="deck-card-thumb deck-card-thumb-empty"></div>`;
  }
  const label =
    thumbnail.kind === "commander"
      ? `Commander : ${thumbnail.name || "deck"}`
      : thumbnail.name || "Illustration deck";
  return `<img src="${escapeHtml(thumbnail.image_url)}" alt="${escapeHtml(label)}" loading="lazy" />`;
}

function renderDeckTilePrice(priceEstimate) {
  if (!priceEstimate) {
    return `<div class="deck-tile-price muted">—</div>`;
  }
  return `<div class="deck-tile-price">${money(priceEstimate.total_eur || 0)}</div>`;
}

function formatDeckRelease(releaseDate) {
  if (!releaseDate) {
    return "";
  }
  return releaseDate.slice(0, 4);
}

function renderDeckCard(deck) {
  const ownedClass = deck.owned ? "deck-card is-owned" : "deck-card";
  const importLabel = deck.owned ? "Possede" : "Ajouter";
  const progress =
    deck.total_cards != null
      ? `<span class="deck-collection-progress" data-deck-collection-progress>${deck.collected_cards || 0}/${deck.total_cards}</span>`
      : "";
  return `
    <article class="${ownedClass}" data-deck-file="${escapeHtml(deck.file_name || "")}">
      <div class="deck-card-media">
        <div class="deck-card-thumb">${renderDeckThumbnail(deck.thumbnail)}</div>
        <label class="deck-owned-toggle" title="Deck possede">
          <input
            type="checkbox"
            data-toggle-deck-owned
            data-file-name="${escapeHtml(deck.file_name || "")}"
            ${deck.owned ? "checked" : ""}
            aria-label="Deck possede"
          />
        </label>
      </div>
      <div class="deck-card-body">
        <h3 title="${escapeHtml(deck.name || "")}">${escapeHtml(deck.name)}</h3>
        <div class="deck-card-meta">
          <span>${escapeHtml(deck.code || "")}</span>
          <span>${escapeHtml(formatDeckRelease(deck.release_date))}</span>
          ${progress}
        </div>
        ${renderDeckTilePrice(deck.price_estimate)}
        <div class="deck-card-actions">
          <button class="secondary" type="button" data-preview-deck data-file-name="${escapeHtml(deck.file_name)}">Voir</button>
          <button
            class="primary"
            type="button"
            data-import-deck
            data-import-label="Ajouter"
            data-file-name="${escapeHtml(deck.file_name)}"
            ${deck.owned ? "disabled" : ""}
          >${importLabel}</button>
        </div>
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
    renderDeckPreview({
      ...payload,
      deck: withLocalOwnedState(payload.deck || {}),
    });
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
    <section class="panel deck-preview ${deck.owned ? "is-owned" : ""}" data-deck-file="${escapeHtml(deck.file_name || "")}">
      <label class="deck-owned-toggle check-row">
        <input
          type="checkbox"
          data-toggle-deck-owned
          data-file-name="${escapeHtml(deck.file_name || "")}"
          ${deck.owned ? "checked" : ""}
        />
        <span>Deck possede</span>
      </label>
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
            <button
              class="primary"
              type="button"
              data-import-deck
              data-import-label="Importer ce deck"
              data-file-name="${escapeHtml(deck.file_name)}"
              ${deck.owned ? "disabled" : ""}
            >${deck.owned ? "Possede" : "Importer ce deck"}</button>
            <button class="secondary" type="button" data-order-deck-cardmarket>Commander ce deck (CM)</button>
            <button class="secondary" type="button" data-order-deck-missing-cardmarket>Completer (non possedees)</button>
            <button
              class="secondary"
              type="button"
              data-remove-deck
              data-file-name="${escapeHtml(deck.file_name)}"
            >Retirer de la collection</button>
          </div>
          ${renderCardmarketOrderOptionsBar()}
        </div>
      </div>
      ${renderDeckHistorySection(valuation)}
      ${renderDeckSection("Commander", cardsBySection.commander || [])}
      ${renderDeckSection("Main deck", cardsBySection.mainBoard || [])}
      ${renderDeckSection("Sideboard", cardsBySection.sideBoard || [])}
    </section>
  `;
  $("#deckPreview").querySelectorAll("[data-import-deck]").forEach((button) => {
    button.addEventListener("click", () => importDeck(button.dataset.fileName, button));
  });
  $("#deckPreview").querySelectorAll("[data-remove-deck]").forEach((button) => {
    button.addEventListener("click", () => removeDeck(button.dataset.fileName, button));
  });
  const deckRoot = $("#deckPreview");
  const deckLines = flattenDeckCards(cardsBySection)
    .filter((card) => card.scryfall_id)
    .map((card) => ({
      scryfall_id: card.scryfall_id,
      quantity: card.quantity,
      finish: card.finish || "nonfoil",
    }));
  deckRoot.querySelector("[data-order-deck-cardmarket]")?.addEventListener("click", () => {
    openCardmarketOrderPlan({
      lines: deckLines,
      ...readCardmarketOrderOptionsFrom(deckRoot),
    }).catch((error) => toast(error.message));
  });
  deckRoot.querySelector("[data-order-deck-missing-cardmarket]")?.addEventListener("click", () => {
    openCardmarketOrderPlan({
      lines: deckLines,
      only_missing: true,
      ...readCardmarketOrderOptionsFrom(deckRoot),
    }).catch((error) => toast(error.message));
  });
  bindDeckChartInteractions($("#deckPreview"), valuation.history || []);
  bindDeckOwnedToggles($("#deckPreview"));
  bindCardOpen($("#deckPreview"));
  applyDisplayZoom(readStoredDisplayZoom(), { persist: false });
  loadDeckHistoryChart(deck.file_name).catch((error) => toast(error.message));
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

function renderDeckHistorySection(valuation) {
  const missingLines = valuation.missing_lines || [];
  return `
    <div class="deck-section">
      <h3>Suivi prix du deck</h3>
      <p class="muted helper-text">Historique MTGJSON + prix Scryfall du jour. Les options filtrent les cartes sans snapshot historique.</p>
      <div id="deckHistoryChart"></div>
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

function renderDeckHistoryChart(host, valuation) {
  const history = valuation?.history || [];
  const chartOptions = state.deckChart?.chartOptions || readChartHistoryOptions("deck");
  const mapped = history.map((point) => ({
    snapshot_date: point.snapshot_date,
    price: point.total_eur,
  }));
  const range = state.deckChart?.range || readChartRange();
  if (!history.length) {
    host.innerHTML = `
      ${renderChartPanel({
        history: [],
        range,
        currency: valuation?.currency || "EUR",
        sourceKey: "cardmarket",
        sourceInteractive: false,
        chartOptions,
        summaryHtml: `<div class="deck-value chart-panel-summary"><span>Valeur estimee</span><strong>N/A</strong><small>Pas encore de snapshots pour ce deck.</small></div>`,
      })}
    `;
    bindChartHistoryOptions(host, "deck", () => {
      if (state.deckChart?.fileName) {
        loadDeckHistoryChart(state.deckChart.fileName).catch((error) => toast(error.message));
      }
    });
    syncChartPanelHeights(host);
    return;
  }
  host.innerHTML = renderChartPanel({
    history: mapped,
    range,
    currency: valuation?.currency || "EUR",
    sourceKey: "cardmarket",
    sourceInteractive: false,
    chartOptions,
    summaryHtml: `
      <div class="deck-value chart-panel-summary">
        <span>Valeur estimee (${escapeHtml(valuation?.currency || "EUR")})</span>
        <strong>${formatChartMoney(valuation?.current_total_eur ?? 0, valuation?.currency || "EUR")}</strong>
        <small>${renderHistorySummary(valuation, chartOptions)}</small>
      </div>
    `,
  });
  bindChartHistoryOptions(host, "deck", () => {
    if (state.deckChart?.fileName) {
      loadDeckHistoryChart(state.deckChart.fileName).catch((error) => toast(error.message));
    }
  });
  bindDeckChartInteractions(host, mapped, range, valuation?.currency || "EUR");
}

async function loadDeckHistoryChart(fileName) {
  const host = $("#deckPreview")?.querySelector("#deckHistoryChart");
  if (!host || !fileName) {
    return;
  }
  const chartOptions = readChartHistoryOptions("deck");
  state.deckChart = {
    fileName,
    chartOptions,
    range: state.deckChart?.range || readChartRange(),
    history: state.deckChart?.history || [],
  };
  state.deckChart.chartOptions = chartOptions;
  host.innerHTML = `<p class="muted">Chargement de l'historique...</p>`;
  const query = buildHistoryQueryParams("cardmarket", chartOptions);
  const payload = await api(`/api/decks/history?file_name=${encodeURIComponent(fileName)}&${query}`);
  state.deckChart.history = payload.history || [];
  renderDeckHistoryChart(host, payload);
}

function bindDeckChartInteractions(root, mapped, activeRange, currency = "EUR") {
  if (!state.deckChart) {
    state.deckChart = { history: mapped, range: activeRange || readChartRange(), chartOptions: readChartHistoryOptions("deck") };
  } else {
    state.deckChart.history = mapped;
    state.deckChart.range = activeRange || state.deckChart.range || readChartRange();
  }
  const setRange = (range) => {
    state.deckChart.range = range;
    saveChartRange(range);
    const chartSection = root.querySelector("[data-chart-section]");
    if (chartSection) {
      chartSection.innerHTML = renderInteractiveChart(mapped, range, currency);
      root.querySelectorAll("[data-chart-range]").forEach((tile) => {
        const active = tile.dataset.chartRange === range;
        tile.classList.toggle("is-active", active);
        tile.setAttribute("aria-pressed", active ? "true" : "false");
      });
      bindInteractiveChart(root, mapped, range, currency);
      syncChartPanelHeights(root);
    }
  };
  const periodHost = root.querySelector("[data-period-grid-host]");
  if (periodHost) {
    bindPeriodTiles(periodHost, setRange);
  }
  bindInteractiveChart(root, filterHistoryForChart(mapped, state.deckChart.range), state.deckChart.range, currency);
  syncChartPanelHeights(root);
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

async function removeDeck(fileName, button) {
  try {
    setLoading(button, true, "Retrait...");
    const collection = await api("/api/decks/remove", {
      method: "POST",
      body: JSON.stringify({ file_name: fileName }),
    });
    state.collection = collection;
    renderCollection(collection);
    const info = collection.deck_remove || {};
    const ownedMeta = info.deck || { owned: false };
    rememberOwnedDeck(fileName, false);
    updateCachedDeckOwned(fileName, false, ownedMeta);
    applyDeckOwnedUi(fileName, false, ownedMeta);
    toast(`${info.removed_cards || 0} carte(s) retiree(s) du deck`);
    invalidateCollectionBlocksCache();
    if (state.currentTab === "my-collection") {
      await loadMyCollection();
    }
    const payload = await api(`/api/decks/detail?file_name=${encodeURIComponent(fileName)}`);
    renderDeckPreview({
      ...payload,
      deck: { ...(payload.deck || {}), ...ownedMeta },
    });
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(button, false);
  }
}

async function importDeck(fileName, button) {
  let success = false;
  let ownedMeta = null;
  try {
    setLoading(button, true, "Import...");
    const collection = await api("/api/decks/import", {
      method: "POST",
      body: JSON.stringify({ file_name: fileName }),
    });
    state.collection = collection;
    renderCollection(collection);
    const info = collection.deck_import || {};
    ownedMeta = info.deck || { owned: true, owned_source: "manual" };
    success = true;
    toast(`${info.imported_cards || 0} carte(s) ajoutee(s) — deck marque possede`);
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(button, false);
    if (success) {
      rememberOwnedDeck(fileName, true);
      updateCachedDeckOwned(fileName, true, ownedMeta);
      applyDeckOwnedUi(fileName, true, ownedMeta);
    }
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

let priceArchiveWasRunning = false;
let priceArchivePollTimer = null;

function archiveProgressPercent(status) {
  if (status.phase === "writing" && status.cards_total) {
    return Math.min(100, Math.round(((status.cards_processed || 0) / status.cards_total) * 100));
  }
  if (status.phase === "parsing" && status.uuids_total) {
    return Math.min(99, Math.round(((status.uuids_found || 0) / status.uuids_total) * 100));
  }
  if (status.phase === "downloading") {
    return 12;
  }
  if (status.phase === "preparing" || status.phase === "starting") {
    return 4;
  }
  if (status.running) {
    return 8;
  }
  return 0;
}

function archivePhaseLabel(status) {
  if (status.message) {
    return status.message;
  }
  switch (status.phase) {
    case "starting":
      return "Demarrage de l'archivage...";
    case "preparing":
      return "Preparation des cartes suivies...";
    case "downloading":
      return "Telechargement MTGJSON AllPricesToday (fichier volumineux, le PC peut ralentir)...";
    case "parsing":
      return `Lecture des prix: ${status.uuids_found || 0}/${status.uuids_total || 0} cartes`;
    case "writing":
      return `Ecriture SQLite: ${status.cards_processed || 0}/${status.cards_total || 0} cartes`;
    case "cardmarket_download":
      return "Telechargement du guide Cardmarket...";
    case "cardmarket_mapping":
      return `Mapping Cardmarket: ${status.cardmarket_mapped || 0} produits`;
    case "cardmarket_archive":
      return `Archivage guide CM: ${status.cardmarket_rows_written || 0} lignes`;
    case "cardmarket_retention":
      return "Compaction historique Cardmarket...";
    case "done":
      return "Archivage termine.";
    case "skipped":
      return "Archivage deja effectue aujourd'hui.";
    case "error":
      return status.error ? `Erreur: ${status.error}` : "Erreur d'archivage.";
    default:
      return "Archivage des prix en cours...";
  }
}

function renderPriceArchiveStatus(status) {
  const banner = $("#priceArchiveBanner");
  const message = $("#priceArchiveMessage");
  const progressBar = $("#priceArchiveProgressBar");
  const percentNode = $("#priceArchivePercent");
  const footer = $("#priceArchiveStatus");
  const percent = archiveProgressPercent(status);
  const running = Boolean(status.running);

  if (banner) {
    banner.classList.toggle("hidden", !running);
  }
  document.body.classList.toggle("price-archive-active", running);

  if (message) {
    message.textContent = archivePhaseLabel(status);
  }
  if (progressBar) {
    progressBar.style.width = `${percent}%`;
  }
  if (percentNode) {
    percentNode.textContent = `${percent}%`;
  }
  if (footer) {
    const cm = status.cardmarket || {};
    const cmParts = [];
    if (cm.guide_end_date) {
      cmParts.push(`guide CM ${cm.guide_end_date}`);
    }
    if (cm.products_mapped != null) {
      const coverage =
        cm.mapping_coverage != null ? ` (${Math.round(cm.mapping_coverage * 100)} %)` : "";
      cmParts.push(`${cm.products_mapped} produits mappes${coverage}`);
    }
    if (cm.mapping_low) {
      cmParts.push("mapping < 90 %");
    }
    const cmText = cmParts.length ? ` · ${cmParts.join(" · ")}` : "";
    if (status.last_archive_date) {
      const snapshots = status.snapshots_written ? ` · ${status.snapshots_written} snapshots` : "";
      footer.textContent = `Dernier archivage: ${status.last_archive_date}${snapshots}${cmText}`;
    } else {
      footer.textContent = `Dernier archivage: jamais.${cmText}`;
    }
    footer.classList.toggle("archive-mapping-warning", Boolean(cm.mapping_low));
  }

  if (priceArchiveWasRunning && !running) {
    if (status.error) {
      toast(`Archivage echoue: ${status.error}`);
    } else if (!status.skipped && status.snapshots_written) {
      toast(`Archivage termine: ${status.snapshots_written} snapshots (${status.last_archive_date || ""})`);
    }
  }
  priceArchiveWasRunning = running;
}

async function startDailyPriceArchive(button, { force = false } = {}) {
  try {
    setLoading(button, true, "Archivage...");
    const status = await api("/api/prices/archive", {
      method: "POST",
      body: JSON.stringify({ force }),
    });
    renderPriceArchiveStatus(status);
    schedulePriceArchivePoll(1200);
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(button, false);
  }
}

function schedulePriceArchivePoll(delayMs = 1500) {
  if (priceArchivePollTimer) {
    window.clearTimeout(priceArchivePollTimer);
  }
  priceArchivePollTimer = window.setTimeout(() => {
    pollPriceArchiveStatus().catch((error) => toast(error.message));
  }, delayMs);
}

async function pollPriceArchiveStatus() {
  const status = await api("/api/prices/archive");
  renderPriceArchiveStatus(status);
  if (status.running) {
    schedulePriceArchivePoll(1500);
  }
}

function renderHeaderStats(summary = {}) {
  const totalCardsNode = $("#headerTotalCards");
  const uniqueNode = $("#headerUniqueCards");
  const splashNode = $("#headerUniqueSplash");
  const totalValueNode = $("#headerTotalValue");
  const uniqueValueNode = $("#headerUniqueValue");
  if (totalCardsNode) {
    totalCardsNode.textContent = String(summary.total_cards ?? 0);
  }
  if (uniqueNode) {
    uniqueNode.textContent = String(summary.unique_cards ?? 0);
  }
  if (splashNode) {
    splashNode.textContent = String(summary.unique_splash ?? 0);
  }
  if (totalValueNode) {
    totalValueNode.textContent = money(summary.estimated_value_eur ?? 0);
    totalValueNode.title = "Avec toutes les copies (doublons inclus)";
  }
  if (uniqueValueNode) {
    const withoutDuplicates =
      summary.unique_value_eur != null ? summary.unique_value_eur : summary.estimated_value_eur ?? 0;
    uniqueValueNode.textContent = money(withoutDuplicates);
    uniqueValueNode.title = "Sans doublons (1 exemplaire par ligne possedee)";
  }
}

function renderCollection(collection) {
  renderHeaderStats(collection.summary || {});
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
  const payload = await api(`/api/collection/blocks?catalog=2&_=${Date.now()}`, { cache: "no-store" });
  const categories = payload.categories || [];
  if (!categories.some((category) => category.id === "universes_beyond")) {
    toast("Regroupements absents : redemarrez le serveur (python run_mvp.py)");
  }
  renderCollectionBlocks(categories);
}

function renderCollectionBlocks(categories) {
  const node = $("#collectionBlocksView");
  const blockSetSort = state.collectionBrowse.blockSetSort || "default";
  node.innerHTML = `
    <div class="collection-blocks-toolbar">
      <label class="collection-cards-sort">
        <span>Trier</span>
        <select id="blockSetSort" aria-label="Tri des extensions">
          ${BLOCK_SET_SORT_OPTIONS.map(
            (option) =>
              `<option value="${escapeHtml(option.value)}" ${option.value === blockSetSort ? "selected" : ""}>${escapeHtml(option.label)}</option>`,
          ).join("")}
        </select>
      </label>
    </div>
    ${categories
      .map(
        (category) => `
      <section class="block-category ${category.group === "franchise" ? "block-category-franchise" : ""}">
        <button class="block-category-header" type="button" data-toggle-category="${escapeHtml(category.id)}">
          <span>${escapeHtml(category.label)}</span>
          <span class="block-count">${category.count}</span>
        </button>
        <div class="block-grid" id="category-${escapeHtml(category.id)}">
          ${sortBlockSets(category.sets || [], blockSetSort).map(renderBlockTile).join("")}
        </div>
      </section>
    `,
      )
      .join("")}
  `;

  node.querySelector("#blockSetSort")?.addEventListener("change", (event) => {
    state.collectionBrowse.blockSetSort = event.currentTarget.value;
    renderCollectionBlocks(categories);
  });

  node.querySelectorAll("[data-open-set]").forEach((button) => {
    button.addEventListener("click", () => openCollectionSet(button.dataset.setCode, button.dataset.setName));
  });
  node.querySelectorAll("[data-toggle-category]").forEach((button) => {
    button.addEventListener("click", () => {
      const target = $(`#category-${button.dataset.toggleCategory}`);
      target.classList.toggle("collapsed");
    });
  });
  bindSetIcons(node);
  focusCollectionBlockTile();
}

function focusCollectionBlockTile() {
  const focus = state.collectionBrowse.pendingBlockFocus;
  if (!focus?.blockId || !focus?.setCode) {
    return;
  }
  const grid = document.getElementById(`category-${focus.blockId}`);
  if (grid) {
    grid.classList.remove("collapsed");
  }
  const tile = document.querySelector(
    `#category-${CSS.escape(focus.blockId)} [data-set-code="${CSS.escape(focus.setCode)}"]`,
  );
  if (tile) {
    tile.classList.add("block-tile-focus");
    tile.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => tile.classList.remove("block-tile-focus"), 3500);
  }
  state.collectionBrowse.pendingBlockFocus = null;
}

async function openCatalogLocation(block) {
  const setCode = String(block.setCode || block.set_code || "").toUpperCase();
  const setName = block.setName || block.set_name || setCode;
  const sectionCode = block.sectionCode || block.section_code;
  const blockId = block.blockId || block.id;
  if (!setCode) {
    return;
  }

  if (blockId) {
    state.collectionBrowse.pendingBlockFocus = {
      blockId,
      setCode,
    };
  }

  switchTab("collection");
  state.collectionBrowse.setCode = setCode;
  state.collectionBrowse.setName = setName;

  const targetSection = sectionCode ? String(sectionCode).toUpperCase() : null;

  try {
    const payload = await api(`/api/collection/${encodeURIComponent(setCode)}`);
    const sections = payload.sections || [];
    if (targetSection) {
      const section = sections.find((entry) => String(entry.code).toUpperCase() === targetSection);
      state.collectionBrowse.sectionCode = section?.code || targetSection;
      state.collectionBrowse.sectionLabel = section?.label || targetSection;
      await showCollectionLevel("cards");
      return;
    }
    const primary = sections.find((entry) => String(entry.code).toUpperCase() === setCode) || sections[0];
    if (primary) {
      state.collectionBrowse.sectionCode = primary.code;
      state.collectionBrowse.sectionLabel = primary.label;
      await showCollectionLevel("cards");
      return;
    }
    await showCollectionLevel("set");
  } catch (error) {
    toast(error.message);
  }
}

function iconSlugForEntry(entry) {
  const keyrune = String(entry.keyrune_code || "")
    .trim()
    .toLowerCase();
  const code = String(entry.code || "")
    .trim()
    .toLowerCase();
  if (keyrune && keyrune !== "default") {
    return keyrune;
  }
  return code;
}

function monogramSvgDataUrl(label) {
  const text = String(label || "?")
    .slice(0, 4)
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "");
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="46" fill="none" stroke="#ffffff" stroke-width="4"/><text x="50" y="58" text-anchor="middle" font-size="22" font-family="Segoe UI,sans-serif" fill="#ffffff">${text || "?"}</text></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function setIconCandidates(entry) {
  const slug = entry.icon_slug || iconSlugForEntry(entry);
  const code = String(entry.code || "")
    .trim()
    .toLowerCase();
  const seen = new Set();
  const candidates = [];
  const add = (value) => {
    const token = String(value || "")
      .trim()
      .toLowerCase();
    if (!token || seen.has(token)) {
      return;
    }
    seen.add(token);
    candidates.push(`https://svgs.scryfall.io/sets/${token}.svg`);
  };
  add(slug);
  add(code);
  if (slug || code) {
    candidates.push(`/api/set-icons/${encodeURIComponent(slug || code)}.svg`);
    candidates.push(`/cache/set-icons/${encodeURIComponent(slug || code)}.svg`);
  }
  return candidates;
}

function bindSetIcons(root) {
  root.querySelectorAll("img[data-set-icon]").forEach((img) => {
    if (img.dataset.iconBound === "true") {
      return;
    }
    img.dataset.iconBound = "true";
    let candidates = [];
    try {
      candidates = JSON.parse(img.dataset.iconCandidates || "[]");
    } catch {
      candidates = [];
    }
    const fallback = img.dataset.iconFallback || "";
    img.addEventListener("error", () => {
      if (candidates.length) {
        img.src = candidates.shift();
        img.dataset.iconCandidates = JSON.stringify(candidates);
        return;
      }
      if (fallback && img.src !== fallback) {
        img.src = fallback;
      }
    });
  });
}

function htmlAttr(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;");
}

function renderSetIcon(entry, className = "set-tile-icon") {
  const candidates = setIconCandidates(entry);
  const [primary, ...rest] = candidates.length ? candidates : [monogramSvgDataUrl(entry.code)];
  const label = entry.name || entry.code || "Extension";
  const fallback = monogramSvgDataUrl(entry.code);
  return `<img
    class="${className}"
    data-set-icon
    src="${htmlAttr(primary)}"
    alt=""
    title="${htmlAttr(label)}"
    loading="lazy"
    decoding="async"
    data-icon-candidates="${htmlAttr(JSON.stringify(rest))}"
    data-icon-fallback="${htmlAttr(fallback)}"
  />`;
}

function renderBlockTile(entry) {
  const ownedClass = entry.owned_cards ? "block-tile owned" : "block-tile";
  return `
    <button class="${ownedClass}" type="button" data-open-set data-set-code="${escapeHtml(entry.code)}" data-set-name="${escapeHtml(entry.name)}">
      ${renderSetIcon(entry)}
      <div class="block-tile-body">
        <span class="block-tile-code">${escapeHtml(entry.code)}</span>
        <strong>${escapeHtml(entry.name)}</strong>
        <span class="block-tile-meta">${formatSetStats(entry)}</span>
      </div>
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
  { value: "owned_desc", label: "Possede d'abord" },
  { value: "owned_asc", label: "Non possede d'abord" },
  { value: "price_desc", label: "Prix decroissant" },
  { value: "price_asc", label: "Prix croissant" },
  { value: "number_asc", label: "Numero croissant" },
  { value: "number_desc", label: "Numero decroissant" },
  { value: "name_asc", label: "Nom A-Z" },
  { value: "name_desc", label: "Nom Z-A" },
];

const BLOCK_SET_SORT_OPTIONS = [
  { value: "default", label: "Par defaut" },
  { value: "owned_desc", label: "Possede d'abord" },
  { value: "owned_asc", label: "Non possede d'abord" },
];

function sortBlockSets(sets, sortKey) {
  if (sortKey === "owned_desc" || sortKey === "owned_asc") {
    return [...sets].sort((left, right) => {
      const leftOwned = (left.owned_cards || 0) > 0 ? 1 : 0;
      const rightOwned = (right.owned_cards || 0) > 0 ? 1 : 0;
      if (leftOwned !== rightOwned) {
        return sortKey === "owned_desc" ? rightOwned - leftOwned : leftOwned - rightOwned;
      }
      return String(left.name || left.code || "").localeCompare(String(right.name || right.code || ""), "fr");
    });
  }
  return sets;
}

const MY_COLLECTION_SORT_OPTIONS = [
  { value: "name_asc", label: "Nom A-Z" },
  { value: "name_desc", label: "Nom Z-A" },
  { value: "price_desc", label: "Prix decroissant" },
  { value: "price_asc", label: "Prix croissant" },
  { value: "cmc_desc", label: "CMC decroissant" },
  { value: "cmc_asc", label: "CMC croissant" },
  { value: "type_asc", label: "Type A-Z" },
  { value: "type_desc", label: "Type Z-A" },
  { value: "subtype_asc", label: "Sous-type A-Z" },
  { value: "subtype_desc", label: "Sous-type Z-A" },
  { value: "color_asc", label: "Couleur" },
  { value: "color_desc", label: "Couleur (inverse)" },
  { value: "set_asc", label: "Extension A-Z" },
  { value: "set_desc", label: "Extension Z-A" },
  { value: "rarity_asc", label: "Rarete (commune → mythique)" },
  { value: "rarity_desc", label: "Rarete (mythique → commune)" },
  { value: "quantity_desc", label: "Quantite decroissante" },
  { value: "quantity_asc", label: "Quantite croissante" },
  { value: "finish_asc", label: "Finition A-Z" },
  { value: "finish_desc", label: "Finition Z-A" },
  { value: "number_asc", label: "Numero croissant" },
  { value: "number_desc", label: "Numero decroissant" },
];

function renderSortOptions(selectedValue, { includeEmpty = false, options = COLLECTION_SORT_OPTIONS } = {}) {
  const emptyOption = includeEmpty ? `<option value="">—</option>` : "";
  return (
    emptyOption +
    options.map(
      (option) =>
        `<option value="${option.value}" ${option.value === selectedValue ? "selected" : ""}>${option.label}</option>`,
    ).join("")
  );
}

const DISPLAY_ZOOM_PREFS_VERSION_KEY = "mtg_display_zoom_prefs_version";
const DISPLAY_ZOOM_PREFS_VERSION = "cards5-ext5-v1";
const TARGET_CARDS_PER_ROW = 5;
const TARGET_EXTENSIONS_PER_ROW = 5;
const EXTENSION_TILE_CARD_RATIO = TARGET_CARDS_PER_ROW / TARGET_EXTENSIONS_PER_ROW;
const DEFAULT_ZOOM_NUDGE = 0.93;
const DECK_TILE_STORAGE_KEY = "mtg_deck_tile_min";
const CARD_SIZE_STORAGE_KEY = "mtg_catalog_card_min";
const DISPLAY_ZOOM_STORAGE_KEY = "mtg_display_zoom";
const DEFAULT_CATALOG_CARD_SIZE = 110;
const MIN_CATALOG_CARD_SIZE = 50;
const MAX_CATALOG_CARD_SIZE = 480;
const DETAIL_CARD_ZOOM_FACTOR = 1.4;
const DEFAULT_DECK_TILE_SIZE = 156;

function deckTileSizeForCardSize(cardSize) {
  return Math.round(cardSize * (DEFAULT_DECK_TILE_SIZE / DEFAULT_CATALOG_CARD_SIZE));
}

function setCatalogCardSizeVars(sizePx) {
  const size = Math.max(MIN_CATALOG_CARD_SIZE, Math.min(MAX_CATALOG_CARD_SIZE, sizePx));
  document.documentElement.style.setProperty("--catalog-card-min", `${size}px`);
  document.documentElement.style.setProperty("--display-card-size", `${size}px`);
  document.documentElement.style.setProperty(
    "--detail-card-max-width",
    `${Math.round(size * DETAIL_CARD_ZOOM_FACTOR)}px`,
  );
  document.documentElement.style.setProperty(
    "--detail-printing-mini-width",
    `${Math.max(40, Math.round(size * DETAIL_CARD_ZOOM_FACTOR * 0.38))}px`,
  );
  document.documentElement.style.setProperty("--extension-tile-min", `${Math.round(size * EXTENSION_TILE_CARD_RATIO)}px`);
  document.documentElement.style.setProperty("--set-icon-size", `${Math.round(size * 0.36)}px`);
  document.documentElement.style.setProperty(
    "--extension-title-size",
    `${Math.max(0.78, Math.min(1.15, size * 0.0085)).toFixed(2)}rem`,
  );
  document.documentElement.style.setProperty(
    "--extension-meta-size",
    `${Math.max(0.68, Math.min(0.92, size * 0.0068)).toFixed(2)}rem`,
  );
  document.documentElement.style.setProperty(
    "--extension-tile-padding",
    `${Math.max(0.55, Math.min(1.15, size * 0.0075)).toFixed(2)}rem`,
  );
  document.documentElement.style.setProperty(
    "--extension-tile-radius",
    `${Math.max(0.75, Math.min(1.35, size * 0.0095)).toFixed(2)}rem`,
  );
  document.documentElement.style.setProperty("--catalog-price-max", `${Math.min(14, Math.max(10, Math.round(size * 0.06)))}px`);
  document.documentElement.style.setProperty("--catalog-price-min", `${Math.max(8, Math.round(size * 0.045))}px`);
  document.documentElement.style.setProperty("--catalog-qty-btn", `${Math.min(2, Math.max(1, Math.round(size * 0.01 * 100) / 100))}rem`);
  document.documentElement.style.setProperty(
    "--card-title-size",
    `${Math.max(0.82, Math.min(1.08, size * 0.0082)).toFixed(2)}rem`,
  );
  return size;
}

function setDeckTileSizeVars(sizePx) {
  const size = Math.max(MIN_CATALOG_CARD_SIZE, Math.min(MAX_CATALOG_CARD_SIZE, sizePx));
  document.documentElement.style.setProperty("--deck-tile-min", `${size}px`);
  document.documentElement.style.setProperty("--deck-tile-title", `${Math.max(0.76, Math.min(1.05, size * 0.0052)).toFixed(2)}rem`);
  document.documentElement.style.setProperty("--deck-tile-meta", `${Math.max(0.62, Math.min(0.84, size * 0.0043)).toFixed(2)}rem`);
  document.documentElement.style.setProperty("--deck-tile-price", `${Math.max(0.72, Math.min(0.96, size * 0.0049)).toFixed(2)}rem`);
  document.documentElement.style.setProperty("--deck-tile-btn", `${Math.max(0.66, Math.min(0.84, size * 0.0045)).toFixed(2)}rem`);
  return size;
}

function applyDisplayZoom(sizePx, { persist = true } = {}) {
  const cardSize = setCatalogCardSizeVars(sizePx);
  setDeckTileSizeVars(cardSize);
  state.collectionBrowse.cardSize = cardSize;
  state.myCollection.cardSize = cardSize;
  if (persist) {
    localStorage.setItem(DISPLAY_ZOOM_STORAGE_KEY, String(cardSize));
    localStorage.setItem(CARD_SIZE_STORAGE_KEY, String(cardSize));
    localStorage.setItem(DECK_TILE_STORAGE_KEY, String(cardSize));
  }
  const slider = $("#globalDisplayZoomInput");
  if (slider && Number(slider.value) !== cardSize) {
    slider.value = String(cardSize);
  }
  return cardSize;
}

let displayZoomFrame = null;

function previewDisplayZoom(sizePx) {
  applyDisplayZoom(sizePx, { persist: false });
}

function applyDefaultDisplayZoomPreferences() {
  const version = localStorage.getItem(DISPLAY_ZOOM_PREFS_VERSION_KEY);
  if (version === DISPLAY_ZOOM_PREFS_VERSION) {
    return;
  }
  localStorage.removeItem(DISPLAY_ZOOM_STORAGE_KEY);
  localStorage.removeItem(CARD_SIZE_STORAGE_KEY);
  localStorage.removeItem(DECK_TILE_STORAGE_KEY);
  localStorage.setItem(DISPLAY_ZOOM_PREFS_VERSION_KEY, DISPLAY_ZOOM_PREFS_VERSION);
}

function cardSizeForViewportWidth(width) {
  const horizontalPadding = width < 520 ? 32 : width < 900 ? 52 : 68;
  const extensionGap = 11;
  const usable = Math.max(width - horizontalPadding, 280);
  const extensionTile =
    (usable - extensionGap * (TARGET_EXTENSIONS_PER_ROW - 1)) / TARGET_EXTENSIONS_PER_ROW;
  const cardSize = Math.floor((extensionTile / EXTENSION_TILE_CARD_RATIO) * DEFAULT_ZOOM_NUDGE);
  return Math.max(MIN_CATALOG_CARD_SIZE, Math.min(MAX_CATALOG_CARD_SIZE, cardSize));
}

function defaultDisplayZoomForViewport() {
  const width = window.innerWidth;
  if (width < 380) {
    return Math.max(MIN_CATALOG_CARD_SIZE, cardSizeForViewportWidth(width) - 10);
  }
  if (width < 520) {
    return Math.max(MIN_CATALOG_CARD_SIZE, cardSizeForViewportWidth(width) - 5);
  }
  return cardSizeForViewportWidth(width);
}

function readStoredDisplayZoom() {
  applyDefaultDisplayZoomPreferences();
  const stored = parseInt(localStorage.getItem(DISPLAY_ZOOM_STORAGE_KEY) || "", 10);
  if (Number.isFinite(stored)) {
    return stored;
  }
  const legacyCard = parseInt(localStorage.getItem(CARD_SIZE_STORAGE_KEY) || "", 10);
  if (Number.isFinite(legacyCard)) {
    return legacyCard;
  }
  const legacyDeck = parseInt(localStorage.getItem(DECK_TILE_STORAGE_KEY) || "", 10);
  if (Number.isFinite(legacyDeck)) {
    return Math.round(legacyDeck * (DEFAULT_CATALOG_CARD_SIZE / DEFAULT_DECK_TILE_SIZE));
  }
  return defaultDisplayZoomForViewport();
}

function syncDisplayZoomSliderBounds() {
  const slider = $("#globalDisplayZoomInput");
  if (!slider) {
    return;
  }
  slider.min = String(MIN_CATALOG_CARD_SIZE);
  slider.max = String(MAX_CATALOG_CARD_SIZE);
  slider.step = "1";
}

function initDisplayZoom() {
  syncDisplayZoomSliderBounds();
  applyDisplayZoom(readStoredDisplayZoom());
}

function applyCatalogCardSize(sizePx, options = {}) {
  return applyDisplayZoom(sizePx, options);
}

function previewCatalogCardSize(sizePx) {
  previewDisplayZoom(sizePx);
}

function initCatalogCardSize() {
  initDisplayZoom();
}

function waitForPaint() {
  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

async function loadCollectionCards() {
  const sort = buildCollectionSortParam();
  $("#collectionCardsView").innerHTML = `<div class="panel"><p class="muted">Chargement...</p></div>`;
  const payload = await api(
    `/api/collection/${encodeURIComponent(state.collectionBrowse.sectionCode)}/cards?${withDisplayLang({ sort }).toString()}`,
  );
  renderCollectionCards(payload);
}

function buildMyCollectionSortParam() {
  const browse = state.myCollection;
  const primary = browse.sortPrimary || "name_asc";
  if (browse.multiSort && browse.sortSecondary) {
    return `${primary},${browse.sortSecondary}`;
  }
  return primary;
}

async function loadMyCollection() {
  const sort = buildMyCollectionSortParam();
  $("#myCollectionView").innerHTML = `<div class="panel"><p class="muted">Chargement...</p></div>`;
  const payload = await api(`/api/my-collection?${withDisplayLang({ sort }).toString()}`);
  renderMyCollection(payload);
}

async function refreshMyCollectionPrices(onProgress) {
  let offset = 0;
  let total = 0;
  let refreshed = 0;
  let errors = 0;

  while (true) {
    const payload = await api("/api/collection/refresh-prices", {
      method: "POST",
      body: JSON.stringify({ scope: "owned", offset, limit: 75 }),
    });
    const result = payload.refresh || {};
    total = result.cards_total || total;
    refreshed += result.cards_refreshed || 0;
    errors += result.errors || 0;
    if (onProgress) {
      onProgress({ done: result.next_offset || 0, total });
    }
    if (result.done) {
      break;
    }
    offset = result.next_offset || offset + 75;
  }

  return { cards_total: total, cards_refreshed: refreshed, errors };
}

async function adjustOwnedCollectionQty(scryfallId, finish, delta, finishBreakdown) {
  const order = ["nonfoil", "foil", "etched"];
  if (delta > 0) {
    const target =
      order.find((entry) => finishBreakdown && finishBreakdown[entry] !== undefined) ||
      finish ||
      "nonfoil";
    return adjustCollectionQty(scryfallId, target, delta);
  }
  if (finishBreakdown) {
    for (const entry of order) {
      if ((finishBreakdown[entry] || 0) > 0) {
        return adjustCollectionQty(scryfallId, entry, -1);
      }
    }
  }
  return adjustCollectionQty(scryfallId, finish || "nonfoil", delta);
}

function formatMoverChange(value, kind, currency = "EUR", negative = false) {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return "—";
  }
  if (kind === "pct") {
    const sign = amount > 0 ? "+" : "";
    return `${sign}${amount.toFixed(1)} %`;
  }
  const sign = amount > 0 ? "+" : "";
  return `${sign}${formatChartMoney(amount, currency)}`;
}

function renderMoverRow(card, kind, currency, negativeColumn = false) {
  const change = kind === "pct" ? card.change_pct : card.change_flat;
  const changeClass =
    change > 0 ? "mover-change-up" : change < 0 ? "mover-change-down" : "mover-change-flat";
  const image = card.image_url
    ? `<img class="mover-thumb" src="${card.image_url}" alt="" loading="lazy" />`
    : `<div class="mover-thumb mover-thumb-empty"></div>`;
  return `
    <button
      type="button"
      class="mover-row"
      data-mover-open
      data-card-id="${escapeHtml(card.scryfall_id)}"
      data-finish="${escapeHtml(card.finish || "nonfoil")}"
    >
      ${image}
      <span class="mover-copy">
        <strong>${escapeHtml(card.name || card.scryfall_id)}</strong>
        <span class="muted">${escapeHtml((card.set_code || "").toUpperCase())} #${escapeHtml(card.collector_number || "")} · ${escapeHtml(card.finish || "nonfoil")}</span>
        <span class="muted">${formatChartMoney(card.start_price, currency)} → ${formatChartMoney(card.end_price, currency)}</span>
      </span>
      <span class="mover-change ${changeClass}">${formatMoverChange(change, kind, currency, negativeColumn)}</span>
    </button>
  `;
}

function renderMoversColumn(title, cards, currency, kind, negativeColumn = false) {
  return `
    <div class="collection-movers-col">
      <span class="collection-movers-col-label">${escapeHtml(title)}</span>
      ${
        cards?.length
          ? cards.map((card) => renderMoverRow(card, kind, currency, negativeColumn)).join("")
          : `<p class="muted">Aucune carte</p>`
      }
    </div>
  `;
}

function renderCollectionMovers(movers, currency, chartOptions = {}) {
  if (!movers) {
    return "";
  }
  const rangeLabel = CHART_RANGE_OPTIONS.find((option) => option.key === movers.range)?.label || movers.range;
  const hints = [];
  if (chartOptions.excludeNewCards) {
    hints.push("cartes passees de 0 € a un prix exclues");
  }
  if (movers.excluded_by_rarity) {
    hints.push(`${movers.excluded_by_rarity} excl. par rarete`);
  }
  const filterHint = hints.length ? ` · ${hints.join(" · ")}` : "";
  if (!movers.start_date || !movers.end_date) {
    return `
      <section class="collection-movers">
        <h4>Plus fortes variations · ${escapeHtml(rangeLabel)}</h4>
        ${renderMoversOptionsColumn(chartOptions)}
        <p class="muted">Pas assez d'historique pour cette periode et cette source.</p>
      </section>
    `;
  }
  return `
    <section class="collection-movers">
      <h4>Plus fortes variations · ${escapeHtml(rangeLabel)}</h4>
      ${renderMoversOptionsColumn(chartOptions)}
      <p class="muted helper-text">Du ${formatChartDate(movers.start_date)} au ${formatChartDate(movers.end_date)} · cartes avec prix &gt; 0 au debut et a la fin${filterHint}</p>
      <div class="collection-movers-grid">
        ${renderMoversColumn("Hausse (€)", movers.top_flat_gain, currency, "flat")}
        ${renderMoversColumn("Baisse (€)", movers.top_flat_loss, currency, "flat", true)}
        ${renderMoversColumn("Hausse (%)", movers.top_pct_gain, currency, "pct")}
        ${renderMoversColumn("Baisse (%)", movers.top_pct_loss, currency, "pct", true)}
      </div>
    </section>
  `;
}

function bindCollectionMovers(root) {
  root.querySelectorAll("[data-mover-open]").forEach((button) => {
    button.addEventListener("click", () => {
      showCardDetail(button.dataset.cardId, button.dataset.finish || "nonfoil").catch((error) => toast(error.message));
    });
  });
}

const SPECULATIVE_PRESET_OPTIONS = [
  { id: "", label: "Tous signaux" },
  { id: "stable_spike", label: "Spike + stable" },
  { id: "value_avg7", label: "Sous AVG7 + momentum" },
  { id: "breakout_liquid", label: "Breakout liquide" },
];

function renderMarketFilterOptions(options) {
  return `
    <div data-market-filter-host>
      <label class="collection-movers-option">
        <input type="checkbox" data-market-exclude-illiquid ${options.excludeIlliquid ? "checked" : ""} />
        <span>Exclure illiquides</span>
      </label>
      <label class="collection-movers-option">
        <span>Metrique</span>
        <select data-market-metric aria-label="Metrique Cardmarket">
          <option value="trend" ${options.marketMetric === "trend" ? "selected" : ""}>Trend</option>
          <option value="avg7" ${options.marketMetric === "avg7" ? "selected" : ""}>AVG7</option>
        </select>
      </label>
      <label class="collection-movers-option">
        <span>Signal</span>
        <select data-market-preset aria-label="Preset speculation">
          ${SPECULATIVE_PRESET_OPTIONS.map(
            (preset) =>
              `<option value="${escapeHtml(preset.id)}" ${options.speculativePreset === preset.id ? "selected" : ""}>${escapeHtml(preset.label)}</option>`,
          ).join("")}
        </select>
      </label>
    </div>
  `;
}

function renderMarketOptionsPanel({ range, sourceKey, chartOptions, trackedCards }) {
  return `
    <div class="chart-panel market-options-panel" data-market-panel-root>
      <div class="chart-panel-summary-wrap">
        <div class="deck-value chart-panel-summary">
          <span>Cartes eligibles (Strixhaven+, non-foil)</span>
          <strong>${trackedCards != null ? escapeHtml(String(trackedCards)) : "—"}</strong>
        </div>
      </div>
      <div class="chart-panel-options market-panel-options">
        <div class="chart-panel-col">
          <span class="chart-panel-col-label">Periode</span>
          <div data-period-grid-host>${renderChartPeriodColumn([], range)}</div>
        </div>
        <div class="chart-panel-col">
          <span class="chart-panel-col-label">Source</span>
          <div data-chart-source-host>${renderChartSourceColumn(sourceKey, true)}</div>
        </div>
        <div class="chart-panel-col">
          <span class="chart-panel-col-label">Rarete</span>
          ${renderMoversOptionsColumn(chartOptions)}
        </div>
        <div class="chart-panel-col">
          <span class="chart-panel-col-label">Liquidite / signaux</span>
          ${renderMarketFilterOptions(chartOptions)}
        </div>
      </div>
    </div>
  `;
}

function renderMarketSpeculativeSpotlight(movers, currency) {
  const picks = movers?.top_speculative_picks || [];
  if (!movers?.start_date || !movers?.end_date) {
    return "";
  }
  const rangeLabel = CHART_RANGE_OPTIONS.find((option) => option.key === movers.range)?.label || movers.range;
  return `
    <section class="market-speculative-spotlight">
      <div class="market-speculative-head">
        <div>
          <h3>Coup de projecteur — Speculation</h3>
          <p class="muted helper-text">
            Cartes &lt; 2 € au début, hausse ≥ 25 % et ≥ 0,30 € · signaux Cardmarket (AVG7, momentum, spread) · max 10 · ${escapeHtml(rangeLabel)}
          </p>
        </div>
      </div>
      ${
        picks.length
          ? `<div class="market-speculative-grid">${picks
              .map((card) => renderMarketSpeculativeCard(card, currency))
              .join("")}</div>`
          : `<p class="muted">Aucun mouvement speculatif notable sur cette periode (essayez 1 mois ou assouplissez les filtres rarete).</p>`
      }
    </section>
  `;
}

const SPECULATIVE_SIGNAL_LABELS = {
  ancienne: "Ancienne",
  prix_stable: "Prix stable",
  breakout: "Breakout",
  spike_sur_stabilite: "Spike stable",
  sous_avg7: "Sous AVG7",
  momentum: "Momentum",
  spread_etroit: "Spread serré",
};

function renderSpeculativeSignalBadges(signals) {
  const items = (signals || [])
    .map((signal) => SPECULATIVE_SIGNAL_LABELS[signal])
    .filter(Boolean);
  if (!items.length) {
    return "";
  }
  return `<span class="market-speculative-signals">${items
    .map((label) => `<span class="market-speculative-signal">${escapeHtml(label)}</span>`)
    .join("")}</span>`;
}

function renderCardmarketMetrics(metrics, currency = "EUR") {
  if (!metrics) {
    return "";
  }
  const rows = [
    ["Trend", metrics.trend],
    ["Low", metrics.low],
    ["AVG", metrics.avg],
    ["AVG1", metrics.avg1],
    ["AVG7", metrics.avg7],
    ["AVG30", metrics.avg30],
  ].filter(([, value]) => value != null);
  if (!rows.length) {
    return "";
  }
  return `
    <dl class="cardmarket-metrics-grid">
      ${rows
        .map(
          ([label, value]) => `
            <div class="cardmarket-metric">
              <dt>${escapeHtml(label)}</dt>
              <dd>${formatChartMoney(value, currency)}</dd>
            </div>
          `,
        )
        .join("")}
    </dl>
  `;
}

function renderMarketSpeculativeCard(card, currency) {
  const image = card.image_url
    ? `<img class="market-speculative-thumb" src="${card.image_url}" alt="" loading="lazy" />`
    : `<div class="market-speculative-thumb market-speculative-thumb-empty"></div>`;
  const cmMetrics = renderCardmarketMetrics(card.cardmarket_metrics, currency);
  return `
    <button
      type="button"
      class="market-speculative-card"
      data-mover-open
      data-card-id="${escapeHtml(card.scryfall_id)}"
      data-finish="${escapeHtml(card.finish || "nonfoil")}"
    >
      ${image}
      <span class="market-speculative-body">
        <strong>${escapeHtml(card.name || card.scryfall_id)}</strong>
        <span class="muted">${escapeHtml((card.set_code || "").toUpperCase())} #${escapeHtml(card.collector_number || "")}</span>
        ${renderSpeculativeSignalBadges(card.speculative_signals)}
        ${cmMetrics}
        <span class="muted">${formatChartMoney(card.start_price, currency)} → ${formatChartMoney(card.end_price, currency)}</span>
        <span class="market-speculative-changes">
          <span class="mover-change mover-change-up">${formatMoverChange(card.change_pct, "pct", currency)}</span>
          <span class="mover-change mover-change-up">${formatMoverChange(card.change_flat, "flat", currency)}</span>
        </span>
      </span>
    </button>
  `;
}

function renderMarketMovers(movers, currency, chartOptions = {}) {
  if (!movers) {
    return "";
  }
  const rangeLabel = CHART_RANGE_OPTIONS.find((option) => option.key === movers.range)?.label || movers.range;
  const hints = [];
  if (movers.excluded_by_rarity) {
    hints.push(`${movers.excluded_by_rarity} excl. par rarete`);
  }
  if (movers.scope?.label) {
    hints.push(movers.scope.label);
  }
  if (movers.tracked_cards != null) {
    hints.push(`${movers.tracked_cards} cartes avec historique`);
  }
  const filterHint = hints.length ? ` · ${hints.join(" · ")}` : "";
  if (!movers.start_date || !movers.end_date) {
    return `
      <section class="collection-movers market-movers">
        <h4>Variations marche · ${escapeHtml(rangeLabel)}</h4>
        <p class="muted">Pas assez d'historique pour cette periode et cette source.</p>
      </section>
    `;
  }
  return `
    <section class="collection-movers market-movers">
      <h4>Variations marche · ${escapeHtml(rangeLabel)}</h4>
      <p class="muted helper-text">Du ${formatChartDate(movers.start_date)} au ${formatChartDate(movers.end_date)} · non-foil avec prix &gt; 0 au debut et a la fin${filterHint}</p>
      <div class="collection-movers-grid market-movers-grid">
        ${renderMoversColumn("Hausse (€)", movers.top_flat_gain, currency, "flat")}
        ${renderMoversColumn("Baisse (€)", movers.top_flat_loss, currency, "flat", true)}
        ${renderMoversColumn("Hausse (%)", movers.top_pct_gain, currency, "pct")}
        ${renderMoversColumn("Baisse (%)", movers.top_pct_loss, currency, "pct", true)}
        ${renderMoversColumn("Specul. (%)", movers.top_speculative_pct_gain, currency, "pct")}
        ${renderMoversColumn("Premium (€)", movers.top_premium_flat_gain, currency, "flat")}
      </div>
      <p class="muted helper-text market-movers-legend">Specul. : hausse % sur cartes &lt; 2 € au debut · Premium : hausse € sur cartes ≥ 10 € a la fin</p>
    </section>
  `;
}

let marketRequestId = 0;

function marketApiErrorMessage(error) {
  if (error?.message === "Not found") {
    return "API Market indisponible : redemarrez le serveur Python (run_mvp.py ou launch.bat prod).";
  }
  return error?.message || "Erreur API";
}

async function loadMarket() {
  const node = $("#marketView");
  if (!node) {
    return;
  }
  const market = state.market;
  market.loading = true;
  node.innerHTML = `<p class="muted">Chargement du marche...</p>`;
  const source = market.chartSource || readChartSource();
  const chartOptions = market.chartOptions || readChartHistoryOptions("market");
  market.chartOptions = chartOptions;
  const range = market.chartRange || readChartRange();
  const requestId = ++marketRequestId;
  const query = buildHistoryQueryParams(source, chartOptions, range);
  try {
    const health = await api("/api/health");
    if (!health.features?.includes("market")) {
      throw new Error("API Market indisponible : redemarrez le serveur Python (run_mvp.py ou launch.bat prod).");
    }
    const payload = await api(`/api/market/movers?${query}`);
    if (requestId !== marketRequestId) {
      return;
    }
    market.payload = payload;
    if (payload.source_key) {
      market.chartSource = payload.source_key;
    }
    renderMarketScreen(payload);
  } catch (error) {
    const message = marketApiErrorMessage(error);
    if (requestId === marketRequestId) {
      node.innerHTML = `<p class="muted">${escapeHtml(message)}</p>`;
    }
    throw new Error(message);
  } finally {
    if (requestId === marketRequestId) {
      market.loading = false;
    }
  }
}

function renderMarketScreen(payload) {
  const node = $("#marketView");
  const market = state.market;
  const sourceKey = payload?.source_key || market.chartSource || readChartSource();
  market.chartSource = sourceKey;
  const currency = chartSourceMeta(sourceKey).currency;
  const chartOptions = market.chartOptions || readChartHistoryOptions("market");
  const range = market.chartRange || readChartRange();
  node.innerHTML = `
    <div class="panel market-panel">
      <h2>Market</h2>
      <p class="muted helper-text">Variations sur toutes les cartes avec historique de prix (pas seulement votre collection). Perimetre actuel : extensions depuis Strixhaven (2021).</p>
      <div id="marketMoversHost" data-market-panel-root></div>
    </div>
  `;
  const host = node.querySelector("#marketMoversHost");
  host.innerHTML = `
    ${renderMarketOptionsPanel({
      range,
      sourceKey,
      chartOptions,
      trackedCards: payload?.tracked_cards,
    })}
    ${renderMarketSpeculativeSpotlight(payload, currency)}
    ${renderMarketMovers(payload, currency, chartOptions)}
  `;
  bindCollectionMovers(host);
  bindMoversOptions(host, "market", async (nextOptions) => {
    market.chartOptions = nextOptions;
    try {
      await loadMarket();
    } catch (error) {
      toast(error.message);
    }
  }, host);
  bindChartSourceTiles(host.querySelector("[data-chart-source-host]"), async (nextSource) => {
    market.chartSource = nextSource;
    saveChartSource(nextSource);
    try {
      await loadMarket();
    } catch (error) {
      toast(error.message);
    }
  });
  bindPeriodTiles(host.querySelector("[data-period-grid-host]"), async (nextRange) => {
    market.chartRange = nextRange;
    saveChartRange(nextRange);
    try {
      await loadMarket();
    } catch (error) {
      toast(error.message);
    }
  });
  syncChartPanelHeights(host);
}

function renderMyCollectionHistoryChart(node, valuation) {
  const browse = state.myCollection;
  const chartOptions = browse.chartOptions || readChartHistoryOptions("collection");
  const history = valuation?.history || [];
  const chartHost = node.querySelector("#myCollectionHistoryChart");
  if (!chartHost) {
    return;
  }
  const sourceKey = valuation?.source_key || browse.chartSource || readChartSource();
  browse.chartSource = sourceKey;
  const currency = chartSourceMeta(sourceKey).currency;
  const mapped = history.map((point) => ({
    snapshot_date: point.snapshot_date,
    price: point.total_eur,
  }));
  const currentTotal = valuation?.current_total ?? valuation?.current_total_eur;
  chartHost.innerHTML = `${renderChartPanel({
    history: mapped,
    range: browse.chartRange,
    currency,
    sourceKey,
    sourceInteractive: true,
    chartOptions,
    showExcludeAdded: true,
    summaryHtml: `
      <div class="deck-value chart-panel-summary">
        <span>Valeur estimee (${escapeHtml(currency)})</span>
        <strong>${history.length && currentTotal != null ? formatChartMoney(currentTotal, currency) : "N/A"}</strong>
        <small>${renderHistorySummary(valuation, chartOptions)}</small>
      </div>
    `,
  })}<div data-collection-movers-host></div>`;
  const moversHost = chartHost.querySelector("[data-collection-movers-host]");
  if (moversHost) {
    moversHost.innerHTML = renderCollectionMovers(valuation?.movers, currency, chartOptions);
    bindCollectionMovers(moversHost);
    bindMoversOptions(moversHost, "collection", async (nextOptions) => {
      browse.chartOptions = nextOptions;
      try {
        await loadMyCollectionHistory(node);
      } catch (error) {
        toast(error.message);
      }
    }, chartHost);
  }
  bindChartSourceTiles(chartHost.querySelector("[data-chart-source-host]"), async (sourceKey) => {
    browse.chartSource = sourceKey;
    saveChartSource(sourceKey);
    try {
      await loadMyCollectionHistory(node);
    } catch (error) {
      toast(error.message);
    }
  });
  bindChartHistoryOptions(
    chartHost,
    "collection",
    async (nextOptions) => {
      browse.chartOptions = nextOptions;
      try {
        await loadMyCollectionHistory(node);
      } catch (error) {
        toast(error.message);
      }
    },
    { showExcludeAdded: true },
  );
  bindHistoryChartPanel(chartHost, mapped, browse.chartRange, currency, async (range) => {
    browse.chartRange = range;
    saveChartRange(range);
    try {
      await loadMyCollectionHistory(node);
    } catch (error) {
      toast(error.message);
    }
  });
  syncChartPanelHeights(chartHost);
}

function bindHistoryChartPanel(root, mappedHistory, activeRange, currency, onRangeChange) {
  const periodHost = root.querySelector("[data-period-grid-host]");
  if (periodHost) {
    bindPeriodTiles(periodHost, onRangeChange);
  }
  bindInteractiveChart(root, filterHistoryForChart(mappedHistory, activeRange), activeRange, currency);
  syncChartPanelHeights(root);
}

async function loadMyCollectionHistory(node) {
  const chartHost = node.querySelector("#myCollectionHistoryChart");
  if (!chartHost) {
    return;
  }
  const graphSection = chartHost.querySelector("[data-chart-section]");
  if (graphSection) {
    graphSection.innerHTML = `<div class="chart chart-empty"><p class="muted">Chargement...</p></div>`;
  } else {
    chartHost.innerHTML = `<p class="muted">Chargement de l'historique...</p>`;
  }
  const browse = state.myCollection;
  const source = browse.chartSource || readChartSource();
  const chartHostRoot = node.querySelector("#myCollectionHistoryChart");
  const chartOptions = chartHostRoot
    ? readHistoryOptionsFromRoot(chartHostRoot, "collection")
    : browse.chartOptions || readChartHistoryOptions("collection");
  browse.chartOptions = chartOptions;
  const range = browse.chartRange || readChartRange();
  const requestId = ++myCollectionHistoryRequestId;
  const query = buildHistoryQueryParams(source, chartOptions, range);
  const payload = await api(`/api/my-collection/history?${query}`);
  if (requestId !== myCollectionHistoryRequestId) {
    return;
  }
  if (payload.source_key && payload.source_key !== source) {
    return;
  }
  state.myCollection.history = payload;
  renderMyCollectionHistoryChart(node, payload);
}

function renderMyCollection(payload) {
  const summary = payload.summary || {};
  const browse = state.myCollection;
  const node = $("#myCollectionView");
  node.innerHTML = `
    <div class="collection-cards-toolbar my-collection-toolbar">
      <div class="collection-cards-summary">
        ${summary.unique_lines || 0} uniques · ${summary.total_cards || 0} exemplaires · ${money(summary.total_value_eur || 0)}
      </div>
      <div class="collection-cards-controls">
        <button class="secondary my-collection-options-toggle" id="myCollectionOptionsToggle" type="button" aria-expanded="${browse.optionsOpen}">
          Evolution du prix
        </button>
        <label class="collection-cards-sort">
          <span>Trier</span>
          <select id="myCollectionSortPrimary" aria-label="Tri principal">
            ${renderSortOptions(browse.sortPrimary, { options: MY_COLLECTION_SORT_OPTIONS })}
          </select>
        </label>
        <label class="collection-cards-sort check-row collection-multi-sort">
          <input id="myCollectionMultiSort" type="checkbox" ${browse.multiSort ? "checked" : ""} />
          Tri multiple
        </label>
        <label class="collection-cards-sort ${browse.multiSort ? "" : "hidden"}" id="myCollectionSecondarySortWrap">
          <span>Puis</span>
          <select id="myCollectionSortSecondary" aria-label="Tri secondaire" ${browse.multiSort ? "" : "disabled"}>
            ${renderSortOptions(browse.sortSecondary, { includeEmpty: true, options: MY_COLLECTION_SORT_OPTIONS })}
          </select>
        </label>
        <button class="secondary" id="refreshMyCollectionPrices" type="button">Charger les prix</button>
        ${renderCardmarketOrderOptionsBar()}
        <button class="secondary" id="orderMissingCollectionCardmarket" type="button">Completer (non possedees)</button>
      </div>
    </div>
    <div class="panel my-collection-options ${browse.optionsOpen ? "" : "hidden"}" id="myCollectionOptions">
      <h3>Evolution du prix de la collection</h3>
      <p class="muted helper-text">Historique MTGJSON quand disponible, sinon prix Scryfall actuels (meme logique que le total de Ma collection). L'archive quotidienne construit une vraie courbe long terme.</p>
      <div id="myCollectionHistoryChart"></div>
    </div>
    <div class="catalog-card-grid">
      ${(payload.cards || []).map((card) => renderCatalogCard(card, { merged: true })).join("")}
    </div>
  `;

  applyCatalogCardSize(browse.cardSize || readStoredDisplayZoom(), { persist: false });

  node.querySelector("#orderMissingCollectionCardmarket")?.addEventListener("click", () => {
    const missingIds = (payload.cards || []).filter((card) => card.scryfall_id && !card.owned).map((card) => card.scryfall_id);
    if (!missingIds.length) {
      toast("Aucune carte manquante dans cette vue");
      return;
    }
    openCardmarketOrderPlan({
      scryfall_ids: missingIds,
      only_missing: true,
      ...readCardmarketOrderOptionsFrom(node),
    }).catch((error) => toast(error.message));
  });

  node.querySelector("#myCollectionOptionsToggle")?.addEventListener("click", async () => {
    browse.optionsOpen = !browse.optionsOpen;
    node.querySelector("#myCollectionOptions")?.classList.toggle("hidden", !browse.optionsOpen);
    const toggle = node.querySelector("#myCollectionOptionsToggle");
    if (toggle) {
      toggle.setAttribute("aria-expanded", browse.optionsOpen ? "true" : "false");
    }
    if (browse.optionsOpen) {
      try {
        await loadMyCollectionHistory(node);
      } catch (error) {
        const chartHost = node.querySelector("#myCollectionHistoryChart");
        if (chartHost) {
          const graphSection = chartHost.querySelector("[data-chart-section]");
          if (graphSection) {
            graphSection.innerHTML = renderEmptyChart("N/A");
          } else {
            chartHost.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
          }
        }
        toast(error.message);
      }
    }
  });

  const applySort = () => {
    browse.sortPrimary = $("#myCollectionSortPrimary").value;
    browse.sortSecondary = $("#myCollectionSortSecondary").value;
    browse.multiSort = $("#myCollectionMultiSort").checked;
    loadMyCollection().catch((error) => toast(error.message));
  };

  node.querySelector("#myCollectionSortPrimary")?.addEventListener("change", applySort);
  node.querySelector("#myCollectionSortSecondary")?.addEventListener("change", applySort);
  node.querySelector("#myCollectionMultiSort")?.addEventListener("change", (event) => {
    browse.multiSort = event.currentTarget.checked;
    const wrap = node.querySelector("#myCollectionSecondarySortWrap");
    const secondary = node.querySelector("#myCollectionSortSecondary");
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
    loadMyCollection().catch((error) => toast(error.message));
  });

  node.querySelector("#refreshMyCollectionPrices")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    const estimatedTotal = summary.total_cards || summary.unique_lines || 1;
    try {
      setLoading(button, true, "Chargement...");
      setCollectionPriceProgress(0, estimatedTotal, "Chargement des prix de la collection");
      await waitForPaint();
      const refresh = await refreshMyCollectionPrices(({ done, total }) =>
        setCollectionPriceProgress(done, total, "Chargement des prix de la collection"),
      );
      toast(`${refresh.cards_refreshed || 0} / ${refresh.cards_total || 0} prix charges`);
      setCollectionPriceProgress(refresh.cards_total || 0, refresh.cards_total || 1, "Chargement des prix de la collection");
      await new Promise((resolve) => setTimeout(resolve, 800));
      invalidateCollectionBlocksCache();
      state.myCollection.history = null;
      const wasOpen = browse.optionsOpen;
      await loadMyCollection();
      if (wasOpen) {
        await loadMyCollectionHistory($("#myCollectionView"));
      }
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
        await adjustOwnedCollectionQty(
          cardNode.dataset.cardId,
          cardNode.dataset.finish || "nonfoil",
          delta,
          parseFinishBreakdown(cardNode.dataset.finishBreakdown),
        );
        invalidateCollectionBlocksCache();
        await loadMyCollection();
      } catch (error) {
        toast(error.message);
      } finally {
        setLoading(target, false);
      }
    });
  });

  bindCardOpen(node);

  if (browse.optionsOpen) {
    loadMyCollectionHistory(node).catch((error) => {
      const chartHost = node.querySelector("#myCollectionHistoryChart");
      if (chartHost) {
        chartHost.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
      }
    });
  }
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
      ${renderCardmarketOrderOptionsBar()}
      <button class="secondary" id="orderSetCardmarket" type="button">Commander le set sur Cardmarket</button>
      <button class="secondary" id="refreshSetPrices" type="button">Charger les prix du bloc</button>
    </div>
    <div class="set-section-grid">
      ${payload.sections
        .map(
          (section) => `
          <button class="set-section-tile" type="button" data-open-section data-section-code="${escapeHtml(section.code)}" data-section-label="${escapeHtml(section.label)}">
            ${renderSetIcon(section, "set-section-icon")}
            <div class="set-section-body">
              <strong>${escapeHtml(section.label)}</strong>
              <span>${formatSetStats(section)}</span>
            </div>
          </button>
        `,
        )
        .join("")}
    </div>
  `;
  node.querySelector("#orderSetCardmarket")?.addEventListener("click", () => {
    openCardmarketOrderPlan({
      set_code: state.collectionBrowse.setCode,
      finish: state.collectionBrowse.orderFinish || "nonfoil",
      ...readCardmarketOrderOptionsFrom(node),
    }).catch((error) => toast(error.message));
  });
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
  bindSetIcons(node);
}

function invalidateCollectionBlocksCache() {
  state.collectionBrowse.blocksStale = true;
}

async function requestCardmarketOrderPlan(body) {
  return api("/api/cardmarket/order-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function renderCardmarketOrderOptionsBar() {
  return `
    <div class="cardmarket-order-options" role="group" aria-label="Options commande Cardmarket">
      <label class="check-row"><input type="checkbox" data-cm-order-only-missing /> Manquantes seulement</label>
      <label class="check-row"><input type="checkbox" data-cm-order-playset /> Playset (×4)</label>
      <label>Langue
        <select data-cm-order-lang aria-label="Langue decklist">
          <option value="merge">Auto</option>
          <option value="fr">FR</option>
          <option value="en">EN</option>
        </select>
      </label>
    </div>
  `;
}

function readCardmarketOrderOptionsFrom(root) {
  const scope = root || document;
  return {
    only_missing: Boolean(scope.querySelector("[data-cm-order-only-missing]")?.checked),
    playset: Boolean(scope.querySelector("[data-cm-order-playset]")?.checked),
    display_lang: scope.querySelector("[data-cm-order-lang]")?.value || "merge",
  };
}

function flattenDeckCards(cardsBySection) {
  return Object.values(cardsBySection || {}).flat();
}

function renderCardmarketOrderModal(plan) {
  const existing = document.getElementById("cardmarketOrderModal");
  if (existing) {
    existing.remove();
  }
  const modal = document.createElement("div");
  modal.id = "cardmarketOrderModal";
  modal.className = "cardmarket-order-modal";
  modal.innerHTML = `
    <div class="cardmarket-order-dialog" role="dialog" aria-modal="true" aria-labelledby="cardmarketOrderTitle">
      <header class="cardmarket-order-head">
        <h3 id="cardmarketOrderTitle">Commande Cardmarket</h3>
        <button type="button" class="secondary" data-close-cardmarket-order aria-label="Fermer">×</button>
      </header>
      <p class="muted helper-text">${escapeHtml(plan.note || "")}</p>
      <p><strong>Estimation trend :</strong> ${formatChartMoney(plan.estimated_subtotal_trend, plan.currency || "EUR")} (${plan.priced_lines || 0} ligne(s) tarifées)</p>
      <label class="cardmarket-order-decklist-label">Decklist (My Wants → Add Decklist)</label>
      <textarea class="cardmarket-order-decklist" readonly rows="10">${escapeHtml(plan.decklist_text || "")}</textarea>
      <div class="cardmarket-order-actions">
        <button type="button" class="secondary" data-copy-cardmarket-decklist>Copier la decklist</button>
        <a class="button-link" href="${escapeHtml(plan.wants_url)}" target="_blank" rel="noopener noreferrer">My Wants</a>
        <a class="button-link" href="${escapeHtml(plan.shopping_wizard_url)}" target="_blank" rel="noopener noreferrer">Shopping Wizard</a>
      </div>
      ${
        (plan.products || []).length
          ? `<details class="detail-disclosure"><summary>${plan.products_mapped || 0} produit(s) lié(s)</summary><ul class="cardmarket-order-products">${plan.products
              .slice(0, 40)
              .map(
                (product) =>
                  `<li><a href="${escapeHtml(product.product_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(product.name)}</a> · ${formatChartMoney(product.trend, plan.currency || "EUR")}</li>`,
              )
              .join("")}</ul></details>`
          : ""
      }
    </div>
  `;
  document.body.appendChild(modal);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) {
      modal.remove();
    }
  });
  modal.querySelector("[data-close-cardmarket-order]")?.addEventListener("click", () => modal.remove());
  modal.querySelector("[data-copy-cardmarket-decklist]")?.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(plan.decklist_text || "");
      toast("Decklist copiée");
    } catch (error) {
      toast(error.message || "Copie impossible");
    }
  });
}

async function openCardmarketOrderPlan(body) {
  const plan = await requestCardmarketOrderPlan(body);
  renderCardmarketOrderModal(plan);
}

function bindCatalogCardSelection(root) {
  root.querySelectorAll("[data-catalog-select]").forEach((input) => {
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("change", (event) => {
      const cardId = event.currentTarget.dataset.scryfallId;
      const selected = new Set(state.collectionBrowse.selectedCardIds || []);
      if (event.currentTarget.checked) {
        selected.add(cardId);
      } else {
        selected.delete(cardId);
      }
      state.collectionBrowse.selectedCardIds = [...selected];
      event.currentTarget.closest(".catalog-card")?.classList.toggle("is-selected", event.currentTarget.checked);
    });
  });
}

function renderCollectionCards(payload) {
  const summary = payload.summary || {};
  state.collectionBrowse.cardsTotal = summary.total_cards || 0;
  const browse = state.collectionBrowse;
  const selectedIds = new Set(browse.selectedCardIds || []);
  const sectionCode = browse.sectionCode || browse.setCode;
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
        ${renderCardmarketOrderOptionsBar()}
        <button class="secondary" type="button" data-catalog-select-all>Tout cocher</button>
        <button class="secondary" type="button" data-catalog-select-invert>Inverser</button>
        <button class="secondary" type="button" data-catalog-select-missing>Manquantes du set</button>
        <label class="collection-cards-sort">
          <span>CM finition</span>
          <select id="collectionOrderFinish" aria-label="Finition Cardmarket">
            <option value="nonfoil" ${browse.orderFinish === "nonfoil" ? "selected" : ""}>Non-foil</option>
            <option value="foil" ${browse.orderFinish === "foil" ? "selected" : ""}>Foil</option>
          </select>
        </label>
        <button class="secondary" type="button" id="orderSectionCardmarket">Commander la section</button>
        <button class="secondary" type="button" id="orderSelectionCardmarket">Commander la sélection (${selectedIds.size})</button>
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
            ${renderSortOptions(browse.sortSecondary, { includeEmpty: true })}
          </select>
        </label>
        <button class="secondary" id="refreshSectionPrices" type="button">Charger les prix</button>
      </div>
    </div>
    ${unavailable}
    <div class="catalog-card-grid">
      ${(payload.cards || [])
        .map((card) =>
          renderCatalogCard(card, {
            selectable: true,
            selected: selectedIds.has(card.scryfall_id),
          }),
        )
        .join("")}
    </div>
  `;

  applyDisplayZoom(readStoredDisplayZoom(), { persist: false });

  node.querySelector("#collectionOrderFinish")?.addEventListener("change", (event) => {
    browse.orderFinish = event.currentTarget.value;
  });
  node.querySelector("#orderSectionCardmarket")?.addEventListener("click", () => {
    openCardmarketOrderPlan({
      section_code: sectionCode,
      finish: browse.orderFinish || "nonfoil",
      ...readCardmarketOrderOptionsFrom(node),
    }).catch((error) => toast(error.message));
  });
  node.querySelector("#orderSelectionCardmarket")?.addEventListener("click", () => {
    const ids = browse.selectedCardIds || [];
    if (!ids.length) {
      toast("Cochez au moins une carte");
      return;
    }
    openCardmarketOrderPlan({
      scryfall_ids: ids,
      finish: browse.orderFinish || "nonfoil",
      ...readCardmarketOrderOptionsFrom(node),
    }).catch((error) => toast(error.message));
  });
  node.querySelector("[data-catalog-select-all]")?.addEventListener("click", () => {
    const cards = payload.cards || [];
    browse.selectedCardIds = cards.filter((card) => card.scryfall_id).map((card) => card.scryfall_id);
    renderCollectionCards(payload);
  });
  node.querySelector("[data-catalog-select-invert]")?.addEventListener("click", () => {
    const cards = payload.cards || [];
    const selected = new Set(browse.selectedCardIds || []);
    cards.forEach((card) => {
      if (!card.scryfall_id) {
        return;
      }
      if (selected.has(card.scryfall_id)) {
        selected.delete(card.scryfall_id);
      } else {
        selected.add(card.scryfall_id);
      }
    });
    browse.selectedCardIds = [...selected];
    renderCollectionCards(payload);
  });
  node.querySelector("[data-catalog-select-missing]")?.addEventListener("click", () => {
    const cards = payload.cards || [];
    browse.selectedCardIds = cards.filter((card) => card.scryfall_id && !card.owned).map((card) => card.scryfall_id);
    renderCollectionCards(payload);
  });
  bindCatalogCardSelection(node);

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
        await adjustOwnedCollectionQty(
          cardNode.dataset.cardId,
          cardNode.dataset.finish || "nonfoil",
          delta,
          parseFinishBreakdown(cardNode.dataset.finishBreakdown),
        );
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
}

function renderCatalogCardPrice(card) {
  const nonfoil = card.price_nonfoil;
  const foil = card.price_foil;
  if (nonfoil != null && foil != null) {
    const title = `${money(nonfoil)} · ${money(foil)}`;
    return `<span class="catalog-card-price catalog-card-price-dual" title="${escapeHtml(title)}"><span class="catalog-card-price-line">${money(nonfoil)}</span><span class="catalog-card-price-line">${money(foil)}</span></span>`;
  }
  const text = formatCatalogPrice(card);
  return `<span class="catalog-card-price" title="${escapeHtml(text)}">${text}</span>`;
}

function parseFinishBreakdown(raw) {
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function catalogOwnedBreakdown(card) {
  if (card?.finish_breakdown && Object.keys(card.finish_breakdown).length) {
    return card.finish_breakdown;
  }
  const quantity = Number(card?.quantity || 0);
  if (quantity > 0 && card?.finish) {
    return { [card.finish]: quantity };
  }
  return null;
}

function formatCatalogQtyBadge(breakdown) {
  if (!breakdown || typeof breakdown !== "object") {
    return "";
  }
  const parts = [];
  const nonfoil = Number(breakdown.nonfoil || 0);
  const foil = Number(breakdown.foil || 0);
  const etched = Number(breakdown.etched || 0);
  if (nonfoil > 0) {
    parts.push(`×${nonfoil}`);
  }
  if (foil > 0) {
    parts.push(`foil×${foil}`);
  }
  if (etched > 0) {
    parts.push(`etched×${etched}`);
  }
  return parts.join(", ");
}

function formatCatalogQtyTitle(breakdown) {
  const label = formatCatalogQtyBadge(breakdown);
  if (!label) {
    return "";
  }
  return `Cette impression : ${label}`;
}

function formatOracleOwnedTotal(oracleOwned) {
  if (!oracleOwned || !oracleOwned.total_copies) {
    return "";
  }
  const total = Number(oracleOwned.total_copies || 0);
  const printings = Number(oracleOwned.printing_count || 0);
  if (total <= 0) {
    return "";
  }
  return `${total} exemplaire${total > 1 ? "s" : ""} sur ${printings} réédition${printings > 1 ? "s" : ""} (toutes versions)`;
}

function renderCatalogCard(card, { merged = false, selectable = false, selected = false } = {}) {
  const ownedClass = card.owned ? "catalog-card owned" : "catalog-card";
  const image = card.image_url
    ? `<img src="${card.image_url}" alt="${escapeHtml(card.name)}" loading="lazy" />`
    : `<div class="catalog-card-placeholder"></div>`;
  const breakdown = catalogOwnedBreakdown(card);
  const primaryFinish =
    card.finish ||
    (breakdown
      ? ["nonfoil", "foil", "etched"].find((finish) => breakdown[finish] > 0)
      : null) ||
    "nonfoil";
  const openAttrs = card.scryfall_id
    ? `data-card-open data-card-id="${escapeHtml(card.scryfall_id)}" data-finish="${escapeHtml(primaryFinish)}" role="button" tabindex="0"`
    : "";
  const footerClass = card.scryfall_id ? "catalog-card-footer" : "catalog-card-footer catalog-card-footer-no-actions";
  const minusBtn = card.scryfall_id
    ? `<button class="catalog-card-qty-btn" type="button" data-qty-delta="-1" aria-label="Retirer une copie">−</button>`
    : "";
  const plusBtn = card.scryfall_id
    ? `<button class="catalog-card-qty-btn" type="button" data-qty-delta="1" aria-label="Ajouter une copie">+</button>`
    : "";
  const qtyLabel = formatCatalogQtyBadge(breakdown);
  const qtyBadge = qtyLabel
    ? `<span class="catalog-card-qty" title="${escapeHtml(formatCatalogQtyTitle(breakdown))}">${escapeHtml(qtyLabel)}</span>`
    : "";
  const breakdownAttr = breakdown
    ? ` data-finish-breakdown="${escapeHtml(JSON.stringify(breakdown))}"`
    : "";
  const selectBox =
    selectable && card.scryfall_id
      ? `<label class="catalog-card-select" title="Sélectionner pour commande Cardmarket">
          <input type="checkbox" data-catalog-select data-scryfall-id="${escapeHtml(card.scryfall_id)}" ${selected ? "checked" : ""} />
        </label>`
      : "";
  return `
    <article class="${ownedClass}${selected ? " is-selected" : ""}" ${openAttrs} data-card-id="${escapeHtml(card.scryfall_id || "")}" data-finish="${escapeHtml(primaryFinish)}"${breakdownAttr}>
      ${selectBox}
      <div class="catalog-card-image-wrap">
        <div class="catalog-card-image">${image}</div>
        ${qtyBadge}
      </div>
      <div class="${footerClass}">
        ${minusBtn}
        ${renderCatalogCardPrice(card)}
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
    const open = () => {
      const cardId = card.dataset.cardId;
      const finish = card.dataset.finish || "nonfoil";
      const navItems = buildCardNavList(root);
      const navIndex = navItems ? navItems.findIndex((item) => item.cardId === cardId && item.finish === finish) : -1;
      showCardDetail(cardId, finish, { navItems, navIndex }).catch((error) => toast(error.message));
    };
    card.addEventListener("click", (event) => {
      const clickedButton = event.target.closest("button");
      if (clickedButton && clickedButton !== card) {
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

async function showCardDetail(cardId, finish, options = {}) {
  const { navItems, navIndex, fromNav = false } = options;
  if (navItems) {
    state.cardDetailNav = {
      items: navItems,
      index: navIndex >= 0 ? navIndex : navItems.findIndex((item) => item.cardId === cardId && item.finish === finish),
    };
  } else if (!fromNav) {
    state.cardDetailNav = null;
  } else if (state.cardDetailNav) {
    const index = state.cardDetailNav.items.findIndex((item) => item.cardId === cardId && item.finish === finish);
    if (index >= 0) {
      state.cardDetailNav.index = index;
    }
  }

  try {
    openCardScreen();
    updateDetailNavControls();
    $("#priceDetails").innerHTML = `<p class="muted">Chargement de la fiche...</p>`;
    const historyLang = readDisplayLang();
    const payload = await api(
      `/api/cards/${cardId}/detail?finish=${encodeURIComponent(finish)}&${withDisplayLang().toString()}`,
    );
    renderCardDetail(payload);
    updateDetailNavControls();
  } catch (error) {
    $("#priceDetails").innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
  }
}

function renderCardDetail(payload) {
  const card = payload.card;
  const details = payload.details || {};
  const history = payload.history || [];
  const rulings = payload.rulings || [];
  const mtgjson = payload.mtgjson || {};
  const collection = payload.collection || {};
  const chartRange = readChartRange();
  const chartSource = readChartSource();
  const sourceMeta = chartSourceMeta(chartSource);
  const historyLang = payload.display_lang || payload.history_lang || readDisplayLang();
  const filteredHistory = filterHistoryBySource(history, chartSource);
  const rangedHistory = filterHistoryForChart(filteredHistory, chartRange, historyLang);
  $("#priceDetails").innerHTML = `
    <section class="detail-hero">
      ${detailImage(card)}
      <div class="detail-hero-panel">
        ${renderDetailHeroAside(
          card,
          details,
          collection,
          card.display_finish || cardAvailableFinishes(card)[0],
          payload.catalog_blocks || [],
          payload.finish_variants || [],
        )}
        ${renderDetailOtherPrintingsMini(
          payload.other_printings || [],
          card.display_finish || "nonfoil",
          payload.oracle_owned,
        )}
      </div>
    </section>
    ${renderDetailVariants(card, collection, card.display_finish || cardAvailableFinishes(card)[0], payload.finish_variants || [])}
    ${renderDetailPriceSection({
      filteredHistory,
      rangedHistory,
      chartRange,
      sourceMeta,
      chartSource,
      mtgjson,
      historyLang,
      cardmarketGuide: payload.cardmarket_guide,
    })}
    ${renderCardText(details)}
    ${renderRulings(rulings)}
  `;
  bindCardDetailInteractions($("#priceDetails"), payload);
  applyDisplayZoom(readStoredDisplayZoom(), { persist: false });
}

function renderPriceSourceLegend(chartSource) {
  const graphLabel =
    chartSource === "cardmarket"
      ? "Graphique = guide Cardmarket quotidien (trend / AVG7 / low)"
      : `Graphique = ${chartSourceMeta(chartSource).label}`;
  return `<p class="price-source-legend muted helper-text">${escapeHtml(graphLabel)} · Prix grille = Scryfall live</p>`;
}

function formatLiveDeltaBadge(guide) {
  if (guide?.live_delta_pct == null) {
    return "";
  }
  const pct = Number(guide.live_delta_pct);
  const sign = pct > 0 ? "+" : "";
  const tone = pct > 5 ? "live-delta-up" : pct < -5 ? "live-delta-down" : "live-delta-neutral";
  return `<span class="live-delta-badge ${tone}">Scryfall ${sign}${pct}% vs trend CM</span>`;
}

const CARDMARKET_METRIC_COLORS = {
  trend: "#54d6a7",
  avg7: "#6b9fff",
  low: "#f0a84a",
};

const CARDMARKET_METRIC_LABELS = {
  trend: "Trend",
  avg7: "AVG7",
  low: "Low",
};

function defaultCardmarketMetricToggles() {
  return { trend: true, avg7: true, low: false };
}

function renderCardmarketMetricToggles(toggles) {
  return `
    <div class="chart-legend cardmarket-metric-toggles" role="group" aria-label="Metriques Cardmarket">
      ${Object.entries(CARDMARKET_METRIC_LABELS)
        .map(
          ([key, label]) => `
            <label class="chart-legend-item">
              <input type="checkbox" data-cm-metric-toggle="${key}" ${toggles[key] ? "checked" : ""} />
              <span class="chart-legend-swatch" style="background:${CARDMARKET_METRIC_COLORS[key]}"></span>
              ${escapeHtml(label)}
            </label>
          `,
        )
        .join("")}
    </div>
  `;
}

function filterSeriesForChart(series, activeRange) {
  return filterHistoryForChart(series || [], activeRange);
}

function renderCardmarketMultiChart(seriesMap, activeRange, toggles, currency = "EUR") {
  const activeSeries = Object.entries(toggles || {})
    .filter(([key, enabled]) => enabled && (seriesMap?.[key] || []).length)
    .map(([key]) => ({
      key,
      points: filterSeriesForChart(seriesMap[key], activeRange),
    }))
    .filter((entry) => entry.points.length);
  if (!activeSeries.length) {
    return renderEmptyChart("N/A");
  }
  const width = CHART_VIEW_WIDTH;
  const height = CHART_VIEW_HEIGHT;
  const pad = CHART_PAD;
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const allValues = activeSeries.flatMap((entry) => entry.points.map((point) => Number(point.price)));
  const rawMin = Math.min(...allValues);
  const rawMax = Math.max(...allValues);
  const spread = rawMax - rawMin || Math.max(rawMax * 0.1, 0.5);
  const min = rawMin - spread * 0.08;
  const max = rawMax + spread * 0.08;
  const range = max - min || 1;
  const allDates = [...new Set(activeSeries.flatMap((entry) => entry.points.map((point) => point.snapshot_date)))].sort();
  const firstMs = chartDateMs(allDates[0]);
  const lastMs = chartDateMs(allDates[allDates.length - 1]);
  const gridCount = 5;
  const gridLines = Array.from({ length: gridCount }, (_, index) => {
    const price = min + (range * index) / (gridCount - 1);
    const y = pad.top + plotH - ((price - min) * plotH) / range;
    return { price, y };
  });
  const labelY = pad.top + plotH + 18;
  const labelIndices = pickChartDateLabelIndices(primary);
  const polylines = activeSeries
    .map((entry) => {
      const points = entry.points.map((point) => {
        const x = chartXForDate(point.snapshot_date, firstMs, lastMs, pad.left, plotW, allDates.length);
        const y = pad.top + plotH - ((Number(point.price) - min) * plotH) / range;
        return { x, y, snapshot_date: point.snapshot_date, price: point.price, metric: entry.key };
      });
      return { key: entry.key, points };
    })
    .filter((entry) => entry.points.length);
  const primary = polylines[0]?.points || [];
  return `
    <div class="chart-interactive" data-chart-interactive data-chart-range="${escapeHtml(activeRange)}" data-cm-multi-chart>
      ${renderCardmarketMetricToggles(toggles)}
      <svg class="chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Courbe Cardmarket multi-metriques">
        ${gridLines
          .map(
            (line) => `
              <line class="chart-grid-line" x1="${pad.left}" y1="${line.y}" x2="${width - pad.right}" y2="${line.y}" />
              <text class="chart-axis-label chart-axis-y" x="${pad.left - 8}" y="${line.y + 4}" text-anchor="end">${formatCompactMoney(line.price, currency)}</text>
            `,
          )
          .join("")}
        ${polylines
          .map(
            (entry) =>
              `<polyline class="chart-line chart-line-cm-${entry.key}" points="${entry.points.map((point) => `${point.x},${point.y}`).join(" ")}" style="stroke:${CARDMARKET_METRIC_COLORS[entry.key]}" />`,
          )
          .join("")}
        ${primary
          .map(
            (point, index) => `
              <circle class="chart-point" cx="${point.x}" cy="${point.y}" r="5" data-chart-index="${index}" data-chart-date="${escapeHtml(point.snapshot_date)}" data-chart-price="${point.price}" />
              ${
                labelIndices.has(index)
                  ? `<text class="chart-axis-label chart-axis-x" x="${point.x}" y="${labelY}" text-anchor="middle">${formatChartDate(point.snapshot_date)}</text>`
                  : ""
              }
            `,
          )
          .join("")}
      </svg>
      <div class="chart-tooltip hidden" data-chart-tooltip></div>
    </div>
  `;
}

function bindCardmarketMetricToggles(root, onChange) {
  root.querySelectorAll("[data-cm-metric-toggle]").forEach((input) => {
    input.addEventListener("change", () => {
      const toggles = { ...(state.cardDetail?.cmMetricToggles || defaultCardmarketMetricToggles()) };
      toggles[input.dataset.cmMetricToggle] = input.checked;
      state.cardDetail.cmMetricToggles = toggles;
      onChange(toggles);
    });
  });
}

function renderDetailCardmarketGuide(guide, chartSource) {
  if (!guide) {
    return `<section class="detail-cardmarket-guide muted"><p>Pas de guide Cardmarket mappe pour cette carte.</p></section>`;
  }
  return `
    <section class="detail-cardmarket-guide">
      <div class="detail-cardmarket-head">
        <h4>Cardmarket</h4>
        <span class="muted">Guide du ${escapeHtml(guide.snapshot_date || "—")}</span>
        ${formatLiveDeltaBadge(guide)}
      </div>
      ${renderCardmarketMetrics(guide.metrics, "EUR")}
      <div class="detail-cardmarket-actions">
        ${
          chartSource !== "cardmarket"
            ? `<button type="button" class="secondary" data-use-cm-chart>Utiliser pour le graphique</button>`
            : ""
        }
        ${
          guide.product_url
            ? `<a class="detail-cardmarket-link" href="${escapeHtml(guide.product_url)}" target="_blank" rel="noopener noreferrer">Ouvrir sur Cardmarket</a>`
            : ""
        }
        ${
          guide.foil_product_url
            ? `<a class="detail-cardmarket-link" href="${escapeHtml(guide.foil_product_url)}" target="_blank" rel="noopener noreferrer">Version foil sur CM</a>`
            : ""
        }
      </div>
    </section>
  `;
}

function renderDetailPriceSection({
  filteredHistory,
  rangedHistory,
  chartRange,
  sourceMeta,
  chartSource,
  mtgjson,
  historyLang,
  cardmarketGuide,
}) {
  const langHint = historyLangHint(historyLang);
  const historyLabel =
    chartSource === "cardmarket"
      ? "Historique Cardmarket (guide quotidien + legacy MTGJSON)"
      : `Historique ${sourceMeta.label}`;
  return `
    <section class="detail-price-section">
      <h3>Suivi des prix</h3>
      ${renderPriceSourceLegend(chartSource)}
      <p class="muted helper-text">${escapeHtml(historyLabel)} (max ${CHART_MAX_POINTS} points affichés). ${escapeHtml(langHint)} Langue globale : ${escapeHtml(displayLangLabel(historyLang))}.</p>
      <div data-cardmarket-guide-host>${renderDetailCardmarketGuide(cardmarketGuide, chartSource)}</div>
      ${renderChartPanel({
        history: filteredHistory,
        range: chartRange,
        currency: sourceMeta.currency,
        sourceKey: chartSource,
        sourceInteractive: true,
        historyLang,
      })}
      ${renderMtgjsonStatus(mtgjson)}
      <details class="detail-disclosure history-list" data-history-list>
        <summary data-history-list-summary>Snapshots prix · ${escapeHtml(sourceMeta.label)} (${sourceMeta.currency})</summary>
        <div data-history-list-body>
        ${renderHistoryRows(rangedHistory, sourceMeta.currency, historyLang)}
        </div>
      </details>
    </section>
  `;
}

function renderDetailOtherPrintingsMini(printings, finish, oracleOwned) {
  if (!printings.length && !(oracleOwned && oracleOwned.total_copies > 0)) {
    return "";
  }
  const totalLine = formatOracleOwnedTotal(oracleOwned);
  return `
    <div class="detail-hero-printings" data-detail-other-printings>
      <div class="detail-printings-head">
        <span class="detail-aside-label">Autres versions (${printings.length})</span>
        ${totalLine ? `<span class="detail-printings-total muted">${escapeHtml(totalLine)}</span>` : ""}
      </div>
      ${
        printings.length
          ? `<div class="detail-printings-mini" role="list" aria-label="Autres versions de la carte">
        ${printings
          .map((printing) => {
            const label = `${printing.set_name || printing.set || ""} #${printing.collector_number || ""}`;
            const ownedLabel = formatCatalogQtyBadge(printing.owned_breakdown);
            const ownedBadge = ownedLabel
              ? `<span class="detail-printing-mini-qty">${escapeHtml(ownedLabel)}</span>`
              : "";
            return `
              <button
                type="button"
                class="detail-printing-mini openable-card ${ownedLabel ? "is-owned" : ""}"
                data-card-open
                data-card-id="${escapeHtml(printing.id)}"
                data-finish="${escapeHtml(printing.display_finish || finish)}"
                title="${escapeHtml(printing.printed_name || printing.name || label)} · ${escapeHtml(label)}${ownedLabel ? ` · ${ownedLabel}` : ""}"
                aria-label="${escapeHtml(printing.printed_name || printing.name || "Carte")} · ${escapeHtml(label)}${ownedLabel ? ` · possédée ${ownedLabel}` : ""}"
              >
                <span class="detail-printing-mini-image-wrap">
                  <img src="${escapeHtml(printing.image_url || "")}" alt="" loading="lazy" />
                  ${ownedBadge}
                </span>
                <span class="detail-printing-mini-meta">${escapeHtml((printing.set || "").toUpperCase())}</span>
              </button>
            `;
          })
          .join("")}
      </div>`
          : `<p class="muted detail-printings-empty">Aucune autre version listée.</p>`
      }
    </div>
  `;
}

function renderDetailExtensions(blocks) {
  if (!blocks.length) {
    return "";
  }
  return `
    <div class="detail-aside-section" data-detail-extensions>
      <span class="detail-aside-label">Extension</span>
      <div class="detail-extension-list">
        ${blocks
          .map(
            (block) => `
              <button
                type="button"
                class="detail-extension-link"
                data-open-catalog-block
                data-block-id="${escapeHtml(block.id)}"
                data-set-code="${escapeHtml(block.set_code)}"
                data-set-name="${escapeHtml(block.set_name || block.set_code)}"
                data-section-code="${escapeHtml(block.section_code || "")}"
              >
                <strong>${escapeHtml(block.set_name || block.set_code)}</strong>
                <span>${escapeHtml(block.label)}${block.section_code && block.section_code !== block.set_code ? ` · ${escapeHtml(block.section_code)}` : ""}</span>
              </button>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

function bindDetailCatalogBlocks(root) {
  root.querySelectorAll("[data-open-catalog-block]").forEach((button) => {
    button.addEventListener("click", () => {
      openCatalogLocation({
        blockId: button.dataset.blockId,
        setCode: button.dataset.setCode,
        setName: button.dataset.setName,
        sectionCode: button.dataset.sectionCode || "",
      }).catch((error) => toast(error.message));
    });
  });
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

function sortHistoryPoints(history) {
  return [...history].sort((left, right) => left.snapshot_date.localeCompare(right.snapshot_date));
}

function lastHistoryPointOnOrBefore(history, cutoffDateStr) {
  let match = null;
  for (const point of history) {
    if (point.snapshot_date <= cutoffDateStr) {
      match = point;
    } else {
      break;
    }
  }
  return match;
}

function computeClientPeriod(history, rangeKey) {
  const sorted = sortHistoryPoints(history);
  if (!sorted.length) {
    return { key: rangeKey, label: CHART_RANGE_OPTIONS.find((item) => item.key === rangeKey)?.label || rangeKey, available: false, message: "Aucun snapshot disponible." };
  }
  const days = CHART_RANGE_DAYS[rangeKey] || 7;
  const latest = sorted[sorted.length - 1];
  const latestDate = new Date(`${latest.snapshot_date}T00:00:00`);
  const cutoff = new Date(latestDate);
  cutoff.setDate(cutoff.getDate() - days);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const start = lastHistoryPointOnOrBefore(sorted, cutoffStr);
  if (!start) {
    return {
      key: rangeKey,
      label: CHART_RANGE_OPTIONS.find((item) => item.key === rangeKey)?.label || rangeKey,
      available: false,
      message: `N/A: historique disponible depuis ${sorted[0].snapshot_date} seulement.`,
      first_available_date: sorted[0].snapshot_date,
      end_date: latest.snapshot_date,
    };
  }
  const startPrice = Number(start.price);
  const endPrice = Number(latest.price);
  const absolute = endPrice - startPrice;
  const percent = startPrice !== 0 ? (absolute / startPrice) * 100 : null;
  return {
    key: rangeKey,
    label: CHART_RANGE_OPTIONS.find((item) => item.key === rangeKey)?.label || rangeKey,
    available: true,
    start_date: start.snapshot_date,
    end_date: latest.snapshot_date,
    absolute_change: absolute,
    percent_change: percent,
    uses_first_available: start.snapshot_date > cutoffStr,
  };
}

function downsampleHistory(points, maxPoints = CHART_MAX_POINTS) {
  if (points.length <= maxPoints) {
    return points;
  }
  const result = [];
  const step = (points.length - 1) / (maxPoints - 1);
  for (let index = 0; index < maxPoints; index += 1) {
    result.push(points[Math.round(index * step)]);
  }
  return result;
}

function filterHistoryForChart(history, rangeKey, historyLang = null) {
  const sorted = sortHistoryPoints(history);
  if (!sorted.length) {
    return [];
  }
  const days = CHART_RANGE_DAYS[rangeKey] || 7;
  const latest = sorted[sorted.length - 1];
  const latestDate = new Date(`${latest.snapshot_date}T00:00:00`);
  const cutoff = new Date(latestDate);
  cutoff.setDate(cutoff.getDate() - days);
  const cutoffStr = cutoff.toISOString().slice(0, 10);
  const filtered = sorted.filter((point) => point.snapshot_date >= cutoffStr);
  const slice = filtered.length ? filtered : sorted.slice(-1);
  if (historyLang === "both") {
    const fr = slice.filter((point) => point.price_lang === "fr");
    const en = slice.filter((point) => point.price_lang === "en");
    const other = slice.filter((point) => point.price_lang !== "fr" && point.price_lang !== "en");
    return [
      ...downsampleHistory(fr),
      ...downsampleHistory(en),
      ...downsampleHistory(other),
    ].sort(
      (left, right) =>
        left.snapshot_date.localeCompare(right.snapshot_date) ||
        String(left.price_lang || "").localeCompare(String(right.price_lang || "")),
    );
  }
  return downsampleHistory(slice);
}

function chartDateMs(dateStr) {
  return new Date(`${dateStr}T00:00:00`).getTime();
}

function chartXForDate(dateStr, firstMs, lastMs, padLeft, plotW, pointCount) {
  if (pointCount <= 1 || lastMs <= firstMs) {
    return padLeft + plotW / 2;
  }
  return padLeft + ((chartDateMs(dateStr) - firstMs) / (lastMs - firstMs)) * plotW;
}

function pickChartDateLabelIndices(points, minGap = CHART_MIN_DATE_LABEL_GAP) {
  if (!points.length) {
    return new Set();
  }
  const indices = new Set([0]);
  let lastX = points[0].x;
  for (let index = 1; index < points.length; index += 1) {
    const isLast = index === points.length - 1;
    if (isLast || points[index].x - lastX >= minGap) {
      indices.add(index);
      lastX = points[index].x;
    }
  }
  return indices;
}

function formatChartDate(dateStr) {
  const parts = String(dateStr || "").split("-");
  if (parts.length !== 3) {
    return dateStr;
  }
  return `${parts[2]}/${parts[1]}`;
}

function formatCompactMoney(value, currency = "EUR") {
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return "—";
  }
  if (currency === "USD") {
    if (amount >= 100) {
      return `${amount.toFixed(0)} $`;
    }
    return usd.format(amount);
  }
  if (amount >= 100) {
    return `${amount.toFixed(0)} €`;
  }
  return money(amount);
}

function renderEmptyChart(label = "N/A") {
  const width = CHART_VIEW_WIDTH;
  const height = CHART_VIEW_HEIGHT;
  const pad = CHART_PAD;
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  return `
    <div class="chart-interactive chart-interactive-empty" data-chart-interactive aria-label="Aucune donnee">
      <svg class="chart chart-empty-state" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img">
        <rect
          x="${pad.left}"
          y="${pad.top}"
          width="${plotW}"
          height="${plotH}"
          fill="none"
          stroke="rgba(184, 173, 201, 0.14)"
          stroke-width="1"
          rx="8"
        />
        <text class="chart-empty-label" x="${width / 2}" y="${height / 2}" text-anchor="middle" dominant-baseline="middle">${escapeHtml(label)}</text>
      </svg>
    </div>
  `;
}

function renderInteractiveChart(history, activeRange, currency = "EUR", historyLang = null) {
  const filtered = filterHistoryForChart(history, activeRange, historyLang);
  if (!filtered.length) {
    return renderEmptyChart("N/A");
  }
  if (historyLang === "both" && filtered.some((point) => point.price_lang === "fr") && filtered.some((point) => point.price_lang === "en")) {
    return renderDualLangChart(filtered, activeRange, currency);
  }

  return renderSingleLangChart(filtered, activeRange, currency);
}

function renderSingleLangChart(filtered, activeRange, currency = "EUR") {
  const width = CHART_VIEW_WIDTH;
  const height = CHART_VIEW_HEIGHT;
  const pad = CHART_PAD;
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const values = filtered.map((point) => Number(point.price));
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const spread = rawMax - rawMin || Math.max(rawMax * 0.1, 0.5);
  const min = rawMin - spread * 0.08;
  const max = rawMax + spread * 0.08;
  const range = max - min || 1;
  const gridCount = 5;
  const gridLines = Array.from({ length: gridCount }, (_, index) => {
    const price = min + (range * index) / (gridCount - 1);
    const y = pad.top + plotH - ((price - min) * plotH) / range;
    return { price, y };
  });
  const firstMs = chartDateMs(filtered[0].snapshot_date);
  const lastMs = chartDateMs(filtered[filtered.length - 1].snapshot_date);
  const points = filtered.map((point) => {
    const x = chartXForDate(point.snapshot_date, firstMs, lastMs, pad.left, plotW, filtered.length);
    const y = pad.top + plotH - ((Number(point.price) - min) * plotH) / range;
    return { x, y, snapshot_date: point.snapshot_date, price: point.price };
  });
  const labelIndices = pickChartDateLabelIndices(points);
  const labelY = pad.top + plotH + 18;

  return `
    <div class="chart-interactive" data-chart-interactive data-chart-range="${escapeHtml(activeRange)}">
      <svg class="chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Courbe des prix">
        ${gridLines
          .map(
            (line) => `
              <line class="chart-grid-line" x1="${pad.left}" y1="${line.y}" x2="${width - pad.right}" y2="${line.y}" />
              <text class="chart-axis-label chart-axis-y" x="${pad.left - 8}" y="${line.y + 4}" text-anchor="end">${formatCompactMoney(line.price, currency)}</text>
            `,
          )
          .join("")}
        <polyline class="chart-line" points="${points.map((point) => `${point.x},${point.y}`).join(" ")}" />
        ${points
          .map(
            (point, index) => `
              <circle
                class="chart-point"
                cx="${point.x}"
                cy="${point.y}"
                r="6"
                data-chart-index="${index}"
                data-chart-date="${escapeHtml(point.snapshot_date)}"
                data-chart-price="${point.price}"
              />
              ${
                labelIndices.has(index)
                  ? `<text class="chart-axis-label chart-axis-x" x="${point.x}" y="${labelY}" text-anchor="middle">${formatChartDate(point.snapshot_date)}</text>`
                  : ""
              }
            `,
          )
          .join("")}
        <line class="chart-crosshair hidden" data-chart-crosshair y1="${pad.top}" y2="${pad.top + plotH}" />
        <circle class="chart-hover-dot hidden" data-chart-hover-dot r="9" />
      </svg>
      <div class="chart-tooltip hidden" data-chart-tooltip></div>
    </div>
  `;
}

function renderDualLangChart(filtered, activeRange, currency = "EUR") {
  const width = CHART_VIEW_WIDTH;
  const height = CHART_VIEW_HEIGHT;
  const pad = CHART_PAD;
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const values = filtered.map((point) => Number(point.price));
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const spread = rawMax - rawMin || Math.max(rawMax * 0.1, 0.5);
  const min = rawMin - spread * 0.08;
  const max = rawMax + spread * 0.08;
  const range = max - min || 1;
  const gridCount = 5;
  const gridLines = Array.from({ length: gridCount }, (_, index) => {
    const price = min + (range * index) / (gridCount - 1);
    const y = pad.top + plotH - ((price - min) * plotH) / range;
    return { price, y };
  });
  const sortedDates = [...new Set(filtered.map((point) => point.snapshot_date))].sort();
  const firstMs = chartDateMs(sortedDates[0]);
  const lastMs = chartDateMs(sortedDates[sortedDates.length - 1]);
  const toSeriesPoints = (series) =>
    sortHistoryPoints(series).map((point) => {
      const x = chartXForDate(point.snapshot_date, firstMs, lastMs, pad.left, plotW, sortedDates.length);
      const y = pad.top + plotH - ((Number(point.price) - min) * plotH) / range;
      return {
        x,
        y,
        snapshot_date: point.snapshot_date,
        price: point.price,
        price_lang: point.price_lang,
      };
    });
  const frPoints = toSeriesPoints(filtered.filter((point) => point.price_lang === "fr"));
  const enPoints = toSeriesPoints(filtered.filter((point) => point.price_lang === "en"));
  const dateMarkers = sortedDates.map((snapshotDate) => ({
    x: chartXForDate(snapshotDate, firstMs, lastMs, pad.left, plotW, sortedDates.length),
    snapshot_date: snapshotDate,
  }));
  const labelIndices = pickChartDateLabelIndices(dateMarkers);
  const labelY = pad.top + plotH + 18;
  const renderSeries = (points, langClass) =>
    points
      .map(
        (point, index) => `
              <circle
                class="chart-point ${langClass}"
                cx="${point.x}"
                cy="${point.y}"
                r="6"
                data-chart-index="${index}"
                data-chart-date="${escapeHtml(point.snapshot_date)}"
                data-chart-price="${point.price}"
                data-chart-lang="${point.price_lang || ""}"
              />
            `,
      )
      .join("");

  return `
    <div class="chart-interactive chart-interactive-dual" data-chart-interactive data-chart-range="${escapeHtml(activeRange)}" data-chart-dual="true">
      <div class="chart-legend" aria-hidden="true">
        <span class="chart-legend-item chart-legend-fr">FR</span>
        <span class="chart-legend-item chart-legend-en">EN</span>
      </div>
      <svg class="chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Courbes des prix FR et EN">
        ${gridLines
          .map(
            (line) => `
              <line class="chart-grid-line" x1="${pad.left}" y1="${line.y}" x2="${width - pad.right}" y2="${line.y}" />
              <text class="chart-axis-label chart-axis-y" x="${pad.left - 8}" y="${line.y + 4}" text-anchor="end">${formatCompactMoney(line.price, currency)}</text>
            `,
          )
          .join("")}
        ${
          frPoints.length
            ? `<polyline class="chart-line chart-line-fr" points="${frPoints.map((point) => `${point.x},${point.y}`).join(" ")}" />`
            : ""
        }
        ${
          enPoints.length
            ? `<polyline class="chart-line chart-line-en" points="${enPoints.map((point) => `${point.x},${point.y}`).join(" ")}" />`
            : ""
        }
        ${renderSeries(frPoints, "chart-point-fr")}
        ${renderSeries(enPoints, "chart-point-en")}
        ${dateMarkers
          .map(
            (marker, index) =>
              labelIndices.has(index)
                ? `<text class="chart-axis-label chart-axis-x" x="${marker.x}" y="${labelY}" text-anchor="middle">${formatChartDate(marker.snapshot_date)}</text>`
                : "",
          )
          .join("")}
        <line class="chart-crosshair hidden" data-chart-crosshair y1="${pad.top}" y2="${pad.top + plotH}" />
        <circle class="chart-hover-dot hidden" data-chart-hover-dot r="9" />
      </svg>
      <div class="chart-tooltip hidden" data-chart-tooltip></div>
    </div>
  `;
}

function bindInteractiveChart(root, history, activeRange, currency = "EUR", historyLang = null) {
  const wrap = root.querySelector("[data-chart-interactive]");
  if (!wrap) {
    return;
  }
  const filtered = filterHistoryForChart(history, activeRange, historyLang);
  const svg = wrap.querySelector("svg");
  const tooltip = wrap.querySelector("[data-chart-tooltip]");
  const crosshair = wrap.querySelector("[data-chart-crosshair]");
  const hoverDot = wrap.querySelector("[data-chart-hover-dot]");
  const points = [...wrap.querySelectorAll(".chart-point")].map((node) => ({
    node,
    x: Number(node.getAttribute("cx")),
    y: Number(node.getAttribute("cy")),
    date: node.dataset.chartDate,
    price: Number(node.dataset.chartPrice),
    lang: node.dataset.chartLang || "",
  }));

  const svgPointToWrap = (x, y) => {
    if (!svg || !wrap) {
      return { left: 0, top: 0 };
    }
    const ctm = svg.getScreenCTM();
    if (!ctm) {
      return { left: 0, top: 0 };
    }
    const pt = svg.createSVGPoint();
    pt.x = x;
    pt.y = y;
    const screen = pt.matrixTransform(ctm);
    const wrapRect = wrap.getBoundingClientRect();
    return {
      left: screen.x - wrapRect.left,
      top: screen.y - wrapRect.top,
    };
  };

  const clientToSvgX = (clientX, clientY) => {
    if (!svg) {
      return 0;
    }
    const ctm = svg.getScreenCTM();
    if (!ctm) {
      return 0;
    }
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    return pt.matrixTransform(ctm.inverse()).x;
  };

  const pointScreenPosition = (point) => svgPointToWrap(point.x, point.y);

  const hideTooltip = () => {
    tooltip?.classList.add("hidden");
    crosshair?.classList.add("hidden");
    hoverDot?.classList.add("hidden");
    points.forEach(({ node }) => {
      node.classList.remove("is-active");
      node.setAttribute("r", "6");
    });
  };

  const showForPoint = (point) => {
    if (!tooltip || !wrap) {
      return;
    }
    points.forEach(({ node }) => {
      node.classList.remove("is-active");
      node.setAttribute("r", "6");
    });
    point.node.classList.add("is-active");
    point.node.setAttribute("r", "8");
    const langSuffix = point.lang ? ` · ${point.lang.toUpperCase()}` : "";
    tooltip.innerHTML = `<strong>${formatChartMoney(point.price, currency)}</strong><span>${escapeHtml(formatChartDate(point.date))} · ${escapeHtml(point.date)}${escapeHtml(langSuffix)}</span>`;
    tooltip.classList.remove("hidden");
    const { left, top } = pointScreenPosition(point);
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
    if (crosshair) {
      crosshair.classList.remove("hidden");
      crosshair.setAttribute("x1", String(point.x));
      crosshair.setAttribute("x2", String(point.x));
    }
    if (hoverDot) {
      hoverDot.classList.remove("hidden");
      hoverDot.setAttribute("cx", String(point.x));
      hoverDot.setAttribute("cy", String(point.y));
    }
  };

  points.forEach((point) => {
    point.node.addEventListener("mouseenter", () => showForPoint(point));
    point.node.addEventListener("focus", () => showForPoint(point));
  });

  svg?.addEventListener("mousemove", (event) => {
    if (!points.length) {
      return;
    }
    const pointerX = clientToSvgX(event.clientX, event.clientY);
    let nearest = points[0];
    let distance = Math.abs(nearest.x - pointerX);
    for (const point of points.slice(1)) {
      const nextDistance = Math.abs(point.x - pointerX);
      if (nextDistance < distance) {
        nearest = point;
        distance = nextDistance;
      }
    }
    showForPoint(nearest);
  });

  wrap.addEventListener("mouseleave", hideTooltip);
  syncChartPanelHeights(root);
}

function renderChartPeriodColumn(periods, activeRange, history = [], currency = "EUR") {
  const serverByKey = Object.fromEntries((periods || []).map((period) => [period.key, period]));
  const tiles = CHART_RANGE_OPTIONS.map((option) => {
    const period = serverByKey[option.key] || computeClientPeriod(history, option.key);
    const isActive = option.key === activeRange;
    const label = escapeHtml(period.label || option.label);
    const rangeHint = period.available
      ? `${period.uses_first_available ? "depuis " : "depuis "}${period.start_date} -> ${period.end_date}`
      : period.message || "";
    if (!period.available) {
      return `
        <button
          type="button"
          class="chart-option-tile period-tile ${isActive ? "is-active" : ""}"
          data-chart-range="${option.key}"
          aria-pressed="${isActive ? "true" : "false"}"
          title="${escapeHtml(rangeHint)}"
        >
          <span>${label}</span>
          <strong>N/A</strong>
        </button>
      `;
    }
    const positive = Number(period.absolute_change || 0) >= 0;
    return `
      <button
        type="button"
        class="chart-option-tile period-tile ${isActive ? "is-active" : ""}"
        data-chart-range="${option.key}"
        aria-pressed="${isActive ? "true" : "false"}"
        title="${escapeHtml(rangeHint)}"
      >
        <span>${label}</span>
        <strong class="${positive ? "positive" : "negative"}">${formatChange(period, currency)}</strong>
      </button>
    `;
  });
  return `<div class="chart-option-grid" role="tablist">${tiles.join("")}</div>`;
}

function buildDetailFinishOptions(card, collection = {}, finishVariants = []) {
  const options = [];
  const seen = new Set();

  const addOption = (entry) => {
    const key = `${entry.cardId}:${entry.finish}`;
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    options.push(entry);
  };

  for (const finish of cardAvailableFinishes(card)) {
    addOption({
      cardId: card.id,
      finish,
      quantity: Number(collection[finish] || 0),
      card,
      isCurrentCard: true,
    });
  }

  for (const variant of finishVariants) {
    const finish = variant.display_finish || cardAvailableFinishes(variant)[0] || "nonfoil";
    addOption({
      cardId: variant.id,
      finish,
      quantity: Number(variant.owned_quantity || 0),
      card: variant,
      isCurrentCard: variant.id === card.id,
    });
  }

  return options.sort((left, right) => {
    const order = { nonfoil: 0, foil: 1, etched: 2 };
    return (order[left.finish] ?? 9) - (order[right.finish] ?? 9);
  });
}

function resolveDetailFinishContext(card, collection = {}, selectedFinish = null, finishVariants = []) {
  const options = buildDetailFinishOptions(card, collection, finishVariants);
  const activeFinish =
    selectedFinish && options.some((option) => option.finish === selectedFinish && option.cardId === card.id)
      ? selectedFinish
      : options.find((option) => option.cardId === card.id)?.finish || options[0]?.finish || "nonfoil";
  const activeOption =
    options.find((option) => option.cardId === card.id && option.finish === activeFinish) ||
    options.find((option) => option.cardId === card.id) ||
    options[0];
  return {
    options,
    activeFinish,
    activeOption,
    multiFinish: options.length > 1,
    quantity: Number(activeOption?.quantity || 0),
  };
}

function renderDetailHeroAside(card, details, collection, selectedFinish, catalogBlocks, finishVariants) {
  const { activeFinish } = resolveDetailFinishContext(card, collection, selectedFinish, finishVariants);
  return `
    <div class="detail-hero-aside">
      <h3>${escapeHtml(card.printed_name || card.name)}</h3>
      <div class="meta">${escapeHtml(card.set_name || card.set || "")} #${escapeHtml(card.collector_number || "")}</div>
      <div class="meta">${escapeHtml(details.type_line || details.printed_type_line || "")}</div>
      ${priceLabel(card.price)}
      <div class="detail-hero-collection" data-detail-collection-compact>
        ${renderDetailCollectionCompact(card, activeFinish, collection)}
      </div>
      ${renderDetailExtensions(catalogBlocks)}
    </div>
  `;
}

function renderDetailCollectionCompact(card, activeFinish, collection = {}) {
  const finishes = ["nonfoil", "foil", "etched"].filter((finish) => cardAvailableFinishes(card).includes(finish));
  const ownedFinishes = finishes.filter((finish) => Number(collection[finish] || 0) > 0);
  const rows = ownedFinishes.length ? ownedFinishes : [activeFinish];

  return `
    <div class="detail-aside-section">
      <span class="detail-aside-label">Collection</span>
      ${rows
        .map((finish) => {
          const quantity = Number(collection[finish] || 0);
          return `
        <div class="detail-finish-row">
          <span class="detail-finish-label">${escapeHtml(finishLabel(finish))}</span>
          ${finishPriceLabel(card, finish)}
          <span class="detail-finish-qty" data-detail-qty="${finish}">${quantity}</span>
          <div class="detail-finish-actions">
            <button class="secondary" type="button" data-detail-qty-delta="-1" data-finish="${finish}" ${quantity <= 0 ? "disabled" : ""}>-</button>
            <button class="secondary" type="button" data-detail-qty-delta="1" data-finish="${finish}">+</button>
          </div>
        </div>
      `;
        })
        .join("")}
    </div>
  `;
}

function renderDetailHiddenQtySpans(options, card, activeFinish) {
  return options
    .filter((option) => !(option.cardId === card.id && option.finish === activeFinish))
    .map(
      (option) => `
        <span class="hidden" data-detail-qty="${option.cardId}:${option.finish}">${option.quantity}</span>
      `,
    )
    .join("");
}

function renderDetailVariants(card, collection = {}, selectedFinish = null, finishVariants = []) {
  const { options, activeFinish, multiFinish } = resolveDetailFinishContext(
    card,
    collection,
    selectedFinish,
    finishVariants,
  );
  if (!multiFinish) {
    return "";
  }
  return `
    <section class="detail-variants" data-detail-collection>
      <h3>Variantes</h3>
      <p class="muted helper-text">Finitions et impressions distinctes pour ce numero de collection.</p>
      <div class="detail-variants-grid" role="group" aria-label="Variantes de la carte">
        ${options
          .map((option) => {
            const isActive = option.cardId === card.id && option.finish === activeFinish;
            const thumb = option.card?.image_url
              ? `<img class="detail-variant-thumb" src="${escapeHtml(option.card.image_url)}" alt="" loading="lazy" />`
              : `<div class="detail-variant-thumb detail-variant-thumb-empty"></div>`;
            return `
              <button
                type="button"
                class="detail-variant-tile ${isActive ? "is-active" : ""}"
                data-detail-finish-select="${option.finish}"
                data-detail-finish-card="${option.cardId}"
                aria-pressed="${isActive ? "true" : "false"}"
              >
                ${thumb}
                <span class="detail-variant-copy">
                  <strong>${escapeHtml(finishLabel(option.finish))}</strong>
                  <span class="muted">x<span data-detail-chip-qty="${option.cardId}:${option.finish}">${option.quantity}</span></span>
                  ${finishPriceLabel(option.card, option.finish)}
                </span>
              </button>
            `;
          })
          .join("")}
      </div>
      ${renderDetailHiddenQtySpans(options, card, activeFinish)}
    </section>
  `;
}

function refreshDetailCollectionSection(root, payload, selectedFinish) {
  const collection = state.cardDetail?.collection || payload.collection || {};
  const finishVariants = payload.finish_variants || [];
  const context = resolveDetailFinishContext(payload.card, collection, selectedFinish, finishVariants);

  const compact = root.querySelector("[data-detail-collection-compact]");
  if (compact) {
    compact.innerHTML = renderDetailCollectionCompact(payload.card, context.activeFinish, collection);
  }

  const variantsHost = root.querySelector("[data-detail-collection]");
  const variantsMarkup = renderDetailVariants(payload.card, collection, selectedFinish, finishVariants);
  if (variantsHost) {
    if (variantsMarkup) {
      const next = document.createElement("div");
      next.innerHTML = variantsMarkup;
      variantsHost.replaceWith(next.firstElementChild);
    } else {
      variantsHost.remove();
    }
  } else if (variantsMarkup) {
    root.querySelector(".detail-hero")?.insertAdjacentHTML("afterend", variantsMarkup);
  }

  bindDetailCollectionControls(root, { ...payload, collection });
}

function updateCardDetailChart(root) {
  if (!state.cardDetail) {
    return;
  }
  const meta = chartSourceMeta(state.cardDetail.source);
  const historyLang = state.cardDetail.historyLang || readDisplayLang();
  const filtered = filterHistoryBySource(state.cardDetail.history, state.cardDetail.source);
  const ranged = filterHistoryForChart(filtered, state.cardDetail.range, historyLang);
  const periodHost = root.querySelector("[data-period-grid-host]");
  if (periodHost) {
    periodHost.innerHTML = renderChartPeriodColumn([], state.cardDetail.range, filtered, meta.currency);
    bindPeriodTiles(periodHost, (range) => {
      state.cardDetail.range = range;
      saveChartRange(range);
      updateCardDetailChart(root);
    });
  }
  const sourceHost = root.querySelector("[data-chart-source-host]");
  if (sourceHost) {
    sourceHost.innerHTML = renderChartSourceGrid(state.cardDetail.source);
    bindChartSourceTiles(sourceHost, (sourceKey) => {
      state.cardDetail.source = sourceKey;
      saveChartSource(sourceKey);
      updateCardDetailChart(root);
    });
  }
  const chartSection = root.querySelector("[data-chart-section]");
  if (chartSection) {
    const cmSeries = state.cardDetail.payload?.cardmarket_series;
    const toggles = state.cardDetail.cmMetricToggles || defaultCardmarketMetricToggles();
    if (state.cardDetail.source === "cardmarket" && cmSeries && Object.values(cmSeries).some((points) => points?.length)) {
      chartSection.innerHTML = renderCardmarketMultiChart(cmSeries, state.cardDetail.range, toggles, meta.currency);
      bindCardmarketMetricToggles(chartSection, () => updateCardDetailChart(root));
      bindInteractiveChart(root, filtered, state.cardDetail.range, meta.currency, historyLang);
    } else {
      chartSection.innerHTML = renderInteractiveChart(filtered, state.cardDetail.range, meta.currency, historyLang);
      bindInteractiveChart(root, filtered, state.cardDetail.range, meta.currency, historyLang);
    }
  }
  const cmGuideHost = root.querySelector("[data-cardmarket-guide-host]");
  if (cmGuideHost) {
    cmGuideHost.innerHTML = renderDetailCardmarketGuide(
      state.cardDetail.payload?.cardmarket_guide,
      state.cardDetail.source,
    );
    cmGuideHost.querySelector("[data-use-cm-chart]")?.addEventListener("click", () => {
      state.cardDetail.source = "cardmarket";
      saveChartSource("cardmarket");
      updateCardDetailChart(root);
    });
  }
  const historyBody = root.querySelector("[data-history-list-body]");
  if (historyBody) {
    historyBody.innerHTML = renderHistoryRows(ranged, meta.currency, historyLang);
  }
  const historyTitle = root.querySelector("[data-history-list-summary]");
  if (historyTitle) {
    historyTitle.textContent = `Snapshots prix · ${meta.label} (${meta.currency})`;
  }
  bindInteractiveChart(root, filtered, state.cardDetail.range, meta.currency, historyLang);
  syncChartPanelHeights(root);
}

function bindDetailCollectionControls(root, payload) {
  const refreshCollectionUi = (collection, selectedFinish = state.cardDetail?.selectedFinish) => {
    state.cardDetail.collection = collection;
    state.cardDetail.payload = { ...state.cardDetail.payload, collection };
    refreshDetailCollectionSection(root, state.cardDetail.payload, selectedFinish);
  };

  root.querySelectorAll("[data-detail-finish-select]").forEach((button) => {
    button.addEventListener("click", () => {
      const finish = button.dataset.detailFinishSelect;
      const targetCardId = button.dataset.detailFinishCard || state.cardDetail?.cardId;
      if (!finish) {
        return;
      }
      if (targetCardId && targetCardId !== state.cardDetail?.cardId) {
        showCardDetail(targetCardId, finish).catch((error) => toast(error.message));
        return;
      }
      if (finish === state.cardDetail?.selectedFinish) {
        return;
      }
      state.cardDetail.selectedFinish = finish;
      refreshDetailCollectionSection(root, payload, finish);
      reloadCardDetailForDisplayLang(root).catch((error) => toast(error.message));
    });
  });

  root.querySelectorAll("[data-detail-qty-delta]").forEach((button) => {
    button.addEventListener("click", async () => {
      const finish = button.dataset.finish || state.cardDetail?.selectedFinish || "nonfoil";
      const delta = Number(button.dataset.detailQtyDelta || 0);
      try {
        setLoading(button, true, delta > 0 ? "+" : "-");
        const summary = await adjustCollectionQty(state.cardDetail.cardId, finish, delta);
        const next = { ...state.cardDetail.collection };
        const current = Number(next[finish] || 0) + delta;
        if (current <= 0) {
          delete next[finish];
        } else {
          next[finish] = current;
        }
        refreshCollectionUi(next, finish);
        invalidateCollectionBlocksCache();
        if (state.currentTab === "my-collection") {
          loadMyCollection().catch((error) => toast(error.message));
        }
        if (summary?.summary) {
          renderHeaderStats(summary.summary);
        }
      } catch (error) {
        toast(error.message);
      } finally {
        setLoading(button, false);
      }
    });
  });
}

async function reloadCardDetailForDisplayLang(root) {
  if (!state.cardDetail?.cardId) {
    return;
  }
  const finish = state.cardDetail.selectedFinish || state.cardDetail.finish || "nonfoil";
  const payload = await api(
    `/api/cards/${state.cardDetail.cardId}/detail?finish=${encodeURIComponent(finish)}&${withDisplayLang().toString()}`,
  );
  renderCardDetail(payload);
}

function bindCardDetailInteractions(root, payload) {
  const defaultFinish = payload.card.display_finish || cardAvailableFinishes(payload.card)[0];
  const historyLang = payload.display_lang || payload.history_lang || readDisplayLang();
  state.cardDetail = {
    cardId: payload.requested_scryfall_id || payload.card.id,
    finish: defaultFinish,
    selectedFinish: defaultFinish,
    history: payload.history || [],
    historyLang,
    languageSiblings: payload.language_siblings || {},
    range: readChartRange(),
    source: readChartSource(),
    collection: payload.collection || {},
    payload,
    cmMetricToggles: defaultCardmarketMetricToggles(),
  };

  bindChartSourceTiles(root.querySelector("[data-chart-source-host]"), (sourceKey) => {
    state.cardDetail.source = sourceKey;
    saveChartSource(sourceKey);
    updateCardDetailChart(root);
  });

  bindDetailCatalogBlocks(root);
  bindCardOpen(root);

  bindPeriodTiles(root.querySelector("[data-period-grid-host]"), (range) => {
    state.cardDetail.range = range;
    saveChartRange(range);
    updateCardDetailChart(root);
  });

  bindInteractiveChart(
    root,
    filterHistoryBySource(state.cardDetail.history, state.cardDetail.source),
    state.cardDetail.range,
    chartSourceMeta(state.cardDetail.source).currency,
    historyLang,
  );

  bindDetailCollectionControls(root, payload);
}

function formatChange(period, currency = "EUR") {
  const absolute = period.absolute_change || 0;
  const percent = period.percent_change;
  const sign = Number(absolute) > 0 ? "+" : "";
  const percentText = percent === null || percent === undefined ? "" : ` (${sign}${Number(percent).toFixed(1)}%)`;
  return `${sign}${formatChartMoney(absolute, currency)}${percentText}`;
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
    <details class="detail-disclosure">
      <summary>Détails Scryfall</summary>
      <div class="detail-disclosure-body">
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
      </div>
    </details>
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
    <details class="detail-disclosure">
      <summary>Explications / rulings</summary>
      <div class="detail-disclosure-body">
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
      </div>
    </details>
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
  if (state.currentTab !== "search") {
    switchTab("search");
  }
  const submit = event.currentTarget.querySelector("button[type='submit']");
  const params = withDisplayLang({
    q: $("#searchInput").value,
    lang: readDisplayLang() === "en" ? "en" : "fr",
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

$("#globalDisplayZoomInput")?.addEventListener("input", (event) => {
  const value = Number(event.currentTarget.value);
  if (displayZoomFrame) {
    cancelAnimationFrame(displayZoomFrame);
  }
  displayZoomFrame = requestAnimationFrame(() => {
    previewDisplayZoom(value);
    displayZoomFrame = null;
  });
});
$("#globalDisplayZoomInput")?.addEventListener("change", (event) => {
  applyDisplayZoom(Number(event.currentTarget.value));
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});

$("#collectionBack").addEventListener("click", backCollectionLevel);
$("#preloadCommanderPrices").addEventListener("click", (event) => startCommanderPreload(event.currentTarget));
$("#archiveDailyPrices")?.addEventListener("click", (event) => startDailyPriceArchive(event.currentTarget));
$("#backFromCard").addEventListener("click", backFromCard);
$("#prevCard").addEventListener("click", () => navigateCardDetail(-1));
$("#nextCard").addEventListener("click", () => navigateCardDetail(1));

document.addEventListener("keydown", (event) => {
  if (state.currentTab !== "prices") {
    return;
  }
  if (event.target.closest("input, textarea, select")) {
    return;
  }
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    navigateCardDetail(-1);
  }
  if (event.key === "ArrowRight") {
    event.preventDefault();
    navigateCardDetail(1);
  }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

runStartupSplash()
  .catch(() => hideStartupSplash())
  .finally(() => {
    const versionNode = document.getElementById("appVersion");
    if (versionNode && window.MTG_APP_VERSION) {
      versionNode.textContent = window.MTG_APP_VERSION;
    }
    loadCollection().catch((error) => toast(error.message));
    initDisplayZoom();
    bindGlobalDisplayLangControl();
    syncGlobalDisplayLangUi();
    pollPreloadStatus();
    pollPriceArchiveStatus().catch(() => {});
  });

let chartPanelResizeFrame = null;
window.addEventListener("resize", () => {
  if (chartPanelResizeFrame) {
    cancelAnimationFrame(chartPanelResizeFrame);
  }
  chartPanelResizeFrame = requestAnimationFrame(() => {
    syncChartPanelHeights();
    chartPanelResizeFrame = null;
  });
});
