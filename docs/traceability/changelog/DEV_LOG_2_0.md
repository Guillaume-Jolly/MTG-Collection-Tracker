# DEV_LOG — MTG Tracker — phase 2.0

**Commit :** 1 commit principal par **X** ; 1 commit atomique par **Y** (REFERENCE `dev-log-et-commits.md`).

**Semver cible :** `2.0.x` (A=2, B=0) — **MEP 2.0.0** livrée 2026-07-10.

---

## ⚠️ Sections ouvertes (X non finalisés)

### X=1 — 2026-07-10 — Kickoff phase 2.0 post-MEP

**But du prompt :** MEP A (2.0.0) — livraison refonte BDD `price_daily`, perf collection/market, audit & backup. Kickoff phase dev 2.0.

| Y | Résumé | Commit | Label UI |
|---|--------|--------|----------|
| 0 | MEP 2.0.0 + kickoff : VERSION-INDEX, project-state, DEV_LOG_2_0, reset X/Y | *(en cours)* | `v2.0.0.01` |

**Validations :** `validate:stack` · `unittest` 109/109 · `health_check_daily` match:true · tag `v2.0.0`

**Risques :** deploy prod manuel · `price_snapshots_legacy` encore en BDD (~3–4 Go récupérables post-archivage)

---

## Historique complété

_(sections X finalisées)_
