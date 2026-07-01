# DEV_LOG — MTG Tracker — phase 0.1

**Statut :** clôturé — MEP **1.0.0** le 2026-06-30.

## Convention (phase 0.1)

| Segment | Signification |
|---------|---------------|
| **SEMVER** | `0.1.x` — MVP / Cardmarket |
| **X / Y** | Session agent (hooks Cursor) |

---

## ⚠️ Sections ouvertes

_(aucune — phase clôturée)_

---

## Historique complété

### Phase 0.1 — clôture MEP 1.0.0 — 2026-06-30

**But :** Première livraison en main — PWA collection, marché Cardmarket, infra versionnement REFERENCE.

| Y | Résumé | Commit | Label UI |
|---|--------|--------|----------|
| 1 | MVP PWA : collection, decks, prix MTGJSON, archivage quotidien | *(local)* | `v0.1.x` |
| 2 | Cardmarket : export, rétention tiered, backfill, index SQL, API séries | *(local)* | `v0.1.x` |
| 3 | Market : AVG7, liquidité, presets signaux, commande CM bulk | *(local)* | `v0.1.x` |
| 4 | Frontend : graphes CM, badge live, panneau archivage | *(local)* | `v0.1.x` |
| 5 | Infra REFERENCE : A.B.C.X.Y, dev-launcher web, git pre-push, docs agent | *(local)* | `v0.1.16.*` |
| 6 | Tests `cardmarket_*`, `test_version`, validate:stack | *(local)* | `v0.1.16.*` |

**Validations :** `npm run validate:stack` OK · tests CM OK · hooks Cursor + git installés.

**Risques / dette :** travail local non commité au moment de la MEP ; `test_shared_catalog` flaky sous Windows (lock SQLite).

**Note :** les sections X=2…13 auto-générées (tests hooks) ont été absorbées dans ce récap — pas de commits atomiques par X sur cette phase.

---

_Journal phase suivante : `DEV_LOG_1_1.md`_
