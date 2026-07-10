# Project state — MTG Tracker

Updated: 2026-07-10

## Phase active

- Branche cible : `feature/2.0`
- Semver : **2.0.0** (A=2, B=0, C=0)
- Label UI : `v2.0.0.01` (X/Y reset post-MEP)
- DEV_LOG actif : `docs/traceability/changelog/DEV_LOG_2_0.md`

## Dernière livraison (MEP)

- **2.0.0** — 2026-07-10 — refonte BDD `price_daily`, perf Ma collection / Market, audit & backup
- Tag : `v2.0.0`
- Deploy : **à faire par l'humain** (prod launcher / PWA locale)
- BDD : ~5,62 Go (`price_daily` + vue compat ; legacy archivable)

## Phase 2.0 — prochaines priorités

1. Retention tiered `price_daily` (60j/jour · 1an/mois · 5ans/an)
2. Archivage `price_snapshots_legacy` → `E:\Backup\` ou `old_1_5/` (documenté)
3. Split fichiers user/catalog (phase C — `DATABASE_ARCHITECTURE.md`)
4. Features produit selon `docs/BACKLOG.md`

## Jalons précédents

| Version | Date | Contenu |
|---------|------|---------|
| 1.0.0 | 2026-06-30 | MEP initiale PWA + Cardmarket |
| 1.1.x–1.6.x | 2026-06→07 | Phase dev post-MEP (journal `DEV_LOG_1_1.md`) |

## Références

- MEP : `C:\Dev\Project\REFERENCE\docs\processes\mep-checklist.md`
- Kickoff : `C:\Dev\Project\REFERENCE\docs\processes\kickoff-nouvelle-phase.md`
- Cleanup 1.5 : `docs/CLEANUP_1_5_MANIFEST.md`
- Archi BDD : `docs/DATABASE_ARCHITECTURE.md`
