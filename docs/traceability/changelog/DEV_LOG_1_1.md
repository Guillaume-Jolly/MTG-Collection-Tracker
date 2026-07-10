# DEV_LOG — MTG Tracker — phase 1.1

**Commit :** 1 commit principal par **X** ; 1 commit atomique par **Y** (REFERENCE `dev-log-et-commits.md`).

**Semver cible :** `1.1.x` (A=1, B=1) — développement post-MEP 1.0.0.

**Statut :** clôturée 2026-07-10 (MEP **2.0.0**). Journal actif : `DEV_LOG_2_0.md`.

---

## Historique complété

### Phase 1.1 — récap clôture (2026-06-30 → 2026-07-10)

**Livrables majeurs :**

- Cardmarket intégration, export, guide daily
- Refonte BDD phase B : `price_daily` (~5,6 Go vs ~11 Go), vue `price_snapshots`, `verify_migration.match: true`
- Perf : `collection_index`, pagination Ma collection, market movers ~2,8 s à froid
- Infra : audit BDD, backup hebdo `E:\`, schedulers prix quotidiens
- Cleanup : `old_1_5/` + `CLEANUP_1_5_MANIFEST.md`

**Commits clés phase B :** `0eacbee`…`f94f724` · push `main` B→1.5→1.6 · MEP A→2.0.0

**Validations finales :** `validate:stack` · 109/109 tests · `health_check_daily` OK

_(Détail granulaire X=2…68 : historique git du fichier avant ce trim.)_
