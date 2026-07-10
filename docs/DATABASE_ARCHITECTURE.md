# Architecture base de donnees — MTG Tracker

Document de reference **avant decoupage**. Derniere revue : 2026-07-09.

## Etat actuel (audit)

| Metrique | Valeur typique (2026-07-09) | Post-migration B (2026-07-10) |
|----------|----------------------------|-------------------------------|
| Fichier | `data/mtg_pwa.sqlite3` | idem |
| Taille | **~10,9 Go** | **~5,6 Go** |
| `price_snapshots` | **~20,3 M lignes** (~99 % du volume) | **vue** sur `price_daily` (EUR actif) |
| `price_snapshots_legacy` | — | table renommée (~20 M lignes, dont CM) |
| `price_daily` | — | **~3,4 M lignes** (2026-03-22 → 2026-07-09) |
| `collection_items` | ~3 k lignes | ~3 k lignes |
| Techno | SQLite 3, WAL, monolithique | idem |

**Verdict court terme :** SQLite reste adapte pour l'app user (collection, wishlist). Le goulot etait la **serie temporelle prix** ; la compaction `price_daily` + vue de compat reduit la taille de moitie.

### Modele `price_daily` (phase B — en place)

- **1 ligne / carte / jour** ; colonnes par source/finish (`sf_cm_*` = EUR Scryfall actif).
- Sources USD MTGJSON (`ck_*`, `tcg_*`, `mp_*`) migrees mais **hors perimetre actif** (`EUR_ONLY_VALUE_COLUMNS`).
- `price_snapshots` = **vue** denormalisant uniquement les colonnes actives (EUR).
- `price_snapshots_legacy` = table historique complete (CM + USD) — archivable apres validation, jamais supprimee (move gitignore).
- Verification : `verify_migration()` compare `legacy_active_rows` (sources EUR actives) vs cellules `price_daily` / vue.

## Cible logique (3 couches)

```text
┌─────────────────────────────────────────────────────────────┐
│  HOT (quotidien, truncate+insert)                           │
│  live_prices_today · cardmarket_guide_today                 │
│  ~40k lignes — requetes app « prix actuel »                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  WARM (retention tiered, SQLite ou ATTACH)                  │
│  price_snapshots 60j/jour · 1an/mois · 5ans/an              │
│  cardmarket_price_guide_daily (+ retention existante)       │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  COLD (append-only, jamais truncate)                        │
│  E:\Backup\MTG Data\mtg_cumulative.sqlite3                  │
│  + futur Parquet/DuckDB par annee                           │
└─────────────────────────────────────────────────────────────┘

┌──────────────────────┐     ┌──────────────────────────────┐
│  mtg_user.sqlite3    │     │  mtg_catalog.sqlite3 (RO)    │
│  collection, wishlist│     │  cards, maps, snapshots warm │
│  index, alertes      │     │  ATTACH depuis l'app         │
└──────────────────────┘     └──────────────────────────────┘
```

## Fichiers cibles (phase B — apres validation modele)

| Fichier | Contenu | Taille estimee |
|---------|---------|----------------|
| `data/mtg_user.sqlite3` | collection, wishlist, binder, alertes, index, app_metadata user | < 50 Mo |
| `data/mtg_catalog.sqlite3` | cards, maps, mtgjson cache, CM guide | ~500 Mo |
| `data/mtg_prices_warm.sqlite3` | price_snapshots retention | variable (objectif < 5 Go) |
| `E:\Backup\MTG Data\mtg_cumulative.sqlite3` | archive insert-only + snapshots hebdo | croissance controlee |

Debut deja en place via `MTG_PWA_PRICES_DB` (ATTACH `shared.*`).

## Tables — role et strategie

### Catalogue / prix (volume)

| Table | Role | Hot | Warm | Cold backup |
|-------|------|-----|------|-------------|
| `price_snapshots` | Historique MTGJSON/Scryfall | non | oui + retention | incrementiel INSERT IGNORE |
| `cardmarket_price_guide_daily` | Historique CM compact | via `_today` futur | oui | incrementiel |
| `cards` | Reference cartes | oui (lecture) | oui | INSERT IGNORE |
| `mtgjson_*` / `cardmarket_product_map` | Maps | oui | oui | INSERT IGNORE |

### App utilisateur (faible volume)

| Table | Role | Backup |
|-------|------|--------|
| `collection_items` | Stock | snapshot hebdo `*_history` (conserve lignes supprimees) |
| `wishlist_items` | Wishlist | idem |
| `price_alerts` / events | Alertes | idem |
| `binder_slots` | Binder | idem |
| `collection_owned_index` | Cache perf | regenerable — pas backup critique |

## Normalisation prevue (gain place)

1. **`source_id`** sur `price_snapshots` (TEXT → tinyint + table `price_sources`)
2. **`live_prices_today`** sans `snapshot_date` (1 ligne/carte/source/finish)
3. **`mtgjson_price_cache`** : extraire retail CM/TCG au lieu de JSON complet
4. **Partition** : `price_snapshots_YYYY` ou fichiers ATTACH par annee

## Audit techno — faut-il migrer ?

| Besoin | SQLite | Alternative |
|--------|--------|-------------|
| Collection / wishlist / alertes | Excellent | PostgreSQL si multi-user cloud |
| Prix live (40k lignes) | Excellent | — |
| Historique 20M+ lignes | Limite (scan, taille) | **TimescaleDB**, **ClickHouse**, **DuckDB** froid |
| Analytics Market (agregats set) | Lent a grande echelle | DuckDB / OLAP |
| Backup local Windows | Fichier unique simple | pg_dump plus lourd |

**Recommandation :**

- **Phase A (now)** : audit + backup E: + warnings — fait
- **Phase B** : `live_prices_today` + retention snapshots (reste SQLite)
- **Phase C** : split `user` / `catalog` / `warm` (3 fichiers SQLite ATTACH)
- **Phase D** (si > 20 Go ou requetes analytics > 5s) : exporter snapshots froids vers **DuckDB** ou migrer serie vers **PostgreSQL + Timescale**

Pas de migration Big Tech imminente : le decoupage fichiers + retention couvre 12–24 mois.

## Backup hebdomadaire (regles)

- **Destination :** `E:\Backup\MTG Data\mtg_cumulative.sqlite3`
- **Frequence :** 1× / semaine max
- **Jamais TRUNCATE** sur le backup
- **Incrementiel :** `INSERT OR IGNORE` (prix, catalogue)
- **Snapshot :** collection/wishlist/alertes avec `backup_run_id` (historique des suppressions)
- **Variable env :** `MTG_BACKUP_ROOT` pour override

Commandes :

```bash
python scripts/db_audit.py
python weekly_backup.py --status
python weekly_backup.py              # si >= 7 jours
python weekly_backup.py --force
python launcher/weekly_backup_scheduler.py
```

## Seuils d'alerte (defaut)

| Scope | Info | Warning | Critical |
|-------|------|---------|----------|
| Base principale | 6 Go | 8 Go | 12 Go |
| Backup cumulatif | — | 15 Go | 40 Go |
| Disque E: libre | — | < 80 Go | < 30 Go |

API : `GET /api/db/audit` · `GET /api/health` (resume) · `GET /api/db/backup-status`

## Ordre d'implementation (ne pas sauter)

1. ✅ Audit + backup + warnings
2. ✅ `price_daily` + bascule requetes live + vue `price_snapshots` (validation EUR)
3. Retention `price_snapshots_legacy` / archivage legacy (move gitignore)
4. Split fichiers user/catalog
5. Export froid Parquet/DuckDB (optionnel)

Chaque etape doit avoir des tests + audit avant la suivante.
