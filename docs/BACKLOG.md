# Backlog MTG Tracker

Fonctionnalités non implémentées (hors scope ou effort majeur). Dernière revue : 2026-07-09.

## Cardmarket / Market / Trading (reporté)

| Idée | Raison report |
|------|----------------|
| **Remplir panier CM automatiquement** | Pas d’API publique Cardmarket ; automation navigateur fragile / ToS |
| **Port réel multi-vendeurs** | Nécessite Shopping Wizard CM ou scraping — hors scope « propre » |
| **Extension navigateur / bookmarklet CM** | Contournement viable mais produit séparé (manifest + maintenance) |
| **Filtre Market par extension / set** | Filtre backend + UI (movers par set_code) — non priorisé |
| **Heatmap extensions (Δ% moyen)** | Agrégation par set + écran dédié |
| **Pagination / cache movers UI** | Cache serveur 6h déjà en place ; virtual scroll non fait |
| **Historique Market mode archive** | Même pipeline lourd que collection archive |
| **Alerte auto « wishlist en baisse »** | Badge visuel sur movers wishlist+baisse fait ; pas d’alerte push dédiée |
| **Listes trade nommées persistées** | Nouveau modèle BDD + CRUD |
| **Import backup JSON** | Export seulement pour l’instant |
| **Sélection trade depuis Wishlist (bulk)** | Ajout unitaire via CM order ; pas de multi-select wishlist → Have |

## UX avancée

| Idée | Raison report |
|------|----------------|
| **Binder drag & drop** | Réorganisation visuelle page/slot (DnD + persistance API) |
| **Tags / dossiers perso** | Nouveau modèle de données (hors binder_name) |
| **Virtual scroll Ma collection** | Refonte pagination → scroll infini + prefetch |
| **Mode mobile dédié** | Refonte CSS/layout responsive large |
| **Historique par carte (sparkline)** | API historique par scryfall_id + rendu fiche |
| **Comparaison 2 decks** | Écran + API dédiée (valeur, overlap, delta collection) |
| **Staples trans-decks** | Analyse agrégée sur tous les decks Commander |
| **Sélection multiple avancée** | Actions bulk (refresh prix ciblé, binder batch) au-delà du trade |

## Data / perf lourde

| Idée | Raison report |
|------|----------------|
| **`live_prices_today` + retention snapshots** | Modele documente dans `docs/DATABASE_ARCHITECTURE.md` — phase B apres validation |
| **Split catalog / user DB** | Phase C — migration ATTACH |
| **Export froid DuckDB/Parquet** | Phase D si analytics > 5s |
| **Archive CM incrémentale** | Refonte pipeline import Cardmarket (~10 Go) |
| **Cache images PWA** | Service worker + stratégie cache Scryfall/local |
| **Header 100 % cache** | `unique_splash` / valeurs sans doublons nécessitent encore scan partiel |

## Qualité

| Idée | Notes |
|------|-------|
| **Tests E2E UI** | Alertes, trade, deck to-buy |
| **Prix d’achat → P&L réel** | `purchase_price` en base, pas d’UI |

## Implémenté (audit BDD + backup — 2026-07-09)

- Audit volumetrie : `GET /api/db/audit`, `python scripts/db_audit.py`
- Warnings taille (header **DB X Go**, logs au demarrage serveur)
- Backup hebdo cumulatif `E:\Backup\MTG Data` (insert only, snapshots collection)
- `docs/DATABASE_ARCHITECTURE.md` — modele cible avant decoupage
- APIs : `/api/db/backup-status`, `POST /api/db/backup-run`
- Planificateur : `launcher/weekly_backup_scheduler.py`, `python weekly_backup.py`

## Implémenté (pack CM / Market / Trade — 2026-07-09)

### Cardmarket commandes
- Fourchette **low → trend** par ligne + sous-total
- **Estimation port** (profils lettre / colissimo / gros lot) + total estimé
- Export **CSV** (idProduct, qty, low, trend) + copie decklist
- Bouton **Shopping Wizard** mis en avant + rappel workflow My Wants
- **Ouvrir produits CM** (max 10 onglets)
- Wishlist → CM avec **finish + qty** (`from_wishlist`)

### Market
- Scope **wishlist** par défaut (+ illiquides exclus par défaut)
- **Commander movers** (liste visible ou sélection)
- **+W** wishlist / **+TW** trade want sur chaque mover
- Badge **Wishlist ↓** (wishlist + colonne baisse)
- Badge **Sous-évaluée** (trend ≥ 1,25× low)
- Affichage **low–trend** sur movers

### Trade
- Listes **Have / Want** séparées
- **Valeur €** trend + **équité** (% delta)
- Export **CSV**, **H:/W:**, **decklist CM** (Want)
- **Commander Want** → modal CM
- **Import liste** adversaire → match collection / → Want
- Fiche carte : boutons Trade Have / Want

### APIs
- `POST /api/trade/summary`
- `POST /api/trade/import-match`
- `POST /api/trade/export` — formats `csv`, `hw`, `mcm`

## Implémenté (phase 3 — 2026-07-09)

- Sync index arrière-plan + lecture non bloquante si index prêt
- Tri prix à jour après refresh CM (dirty scryfall_ids)
- Wishlist : écart budget, tri, alerte ≤ max
- Onglets Alertes (historique + réactivation) et Trade
- Deck « À acheter » + export CM
- Problèmes : fusion doublons, refresh prix stale
- Multi-binders (sélecteur)
- Complétion set : coût estimé manquantes
- Undo qty (Ctrl+Z)
- Header : valeurs depuis cache index si dispo
- Warmup : sync index dirty au démarrage
- Import deck → invalidation index ciblée
- Deck historique : mode Auto/Fast/Archive
- Backup JSON (`GET /api/backup/export`)
- Raccourcis clavier (`?`)
- Sélection trade depuis Ma collection
