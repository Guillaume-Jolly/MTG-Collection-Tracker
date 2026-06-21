const eur = new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" });

const state = {
  collection: null,
  currentTab: "search",
  previousTab: "search",
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
  const collection = await api("/api/collection");
  state.collection = collection;
  renderCollection(collection);
}

function renderDeckResults(decks) {
  const node = $("#deckResults");
  $("#deckPreview").innerHTML = "";
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
        ${commander ? cardImage(commander) : `<div class="card-image"></div>`}
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
  $("#summaryValue").textContent = money(summary.estimated_value_eur || 0);
  $("#summaryCards").textContent = summary.total_cards || 0;
  $("#summaryUnique").textContent = summary.unique_cards || 0;

  const node = $("#collectionList");
  const items = collection.items || [];
  if (!items.length) {
    node.innerHTML = `<div class="panel"><p class="muted">Collection vide. Cherche une carte puis ajoute-la.</p></div>`;
    return;
  }

  node.innerHTML = items.map(renderCollectionItem).join("");
  bindCardOpen(node);
  bindDetailButtons(node);
  node.querySelectorAll("[data-delete]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteItem(button.dataset.itemId, button);
    });
  });
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

$("#deckSearchForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.currentTarget.querySelector("button[type='submit']");
  const params = new URLSearchParams({
    q: $("#deckSearchInput").value,
    limit: "30",
    commander_only: $("#commanderOnlyInput").checked ? "true" : "false",
    hide_collector: $("#hideCollectorInput").checked ? "true" : "false",
    sort: $("#deckSortInput").value,
  });
  try {
    setLoading(submit, true, "Recherche...");
    const payload = await api(`/api/decks/search?${params.toString()}`);
    renderDeckResults(payload.decks);
  } catch (error) {
    toast(error.message);
  } finally {
    setLoading(submit, false);
  }
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => switchTab(button.dataset.tab));
});

$("#refreshPrices").addEventListener("click", (event) => refreshPrices(event.currentTarget));
$("#preloadCommanderPrices").addEventListener("click", (event) => startCommanderPreload(event.currentTarget));
$("#backFromCard").addEventListener("click", backFromCard);

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

loadCollection().catch((error) => toast(error.message));
pollPreloadStatus();
