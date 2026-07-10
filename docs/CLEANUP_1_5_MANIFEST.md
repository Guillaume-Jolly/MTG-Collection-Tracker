# Manifeste cleanup — fin de phase 1.5

**Date :** 2026-07-10  
**Phase quittée :** `1.5` (push `main` B 1.4→1.5, refonte `price_daily`)  
**Archive :** `old_1_5/` (gitignoré — `old_[0-9]*_[0-9]*/`)

## Contenu archivé (move only — jamais supprimé)

| Chemin source | Destination | Motif |
|---------------|-------------|-------|
| `_tmp_apply_index_bench.py` | `old_1_5/bench-diag/` | Bench index collection (one-shot) |
| `_tmp_bench_market.py` | `old_1_5/bench-diag/` | Bench market movers pré-migration |
| `_tmp_bench_mycollection.py` | `old_1_5/bench-diag/` | Bench Ma collection |
| `_tmp_check_archive.py` | `old_1_5/bench-diag/` | Vérif archivage prix |
| `_tmp_cm_aboleth.py` | `old_1_5/bench-diag/` | Debug carte CM |
| `_tmp_db_counts.py` | `old_1_5/bench-diag/` | Comptages BDD one-shot |
| `_tmp_profile_market.py` | `old_1_5/bench-diag/` | Profil perf market |
| `_tmp_profile_mycollection.py` | `old_1_5/bench-diag/` | Profil perf collection |
| `scripts/_bench_now.py` | `old_1_5/bench-diag/` | Bench rapide BDD |
| `scripts/_check_db_state.py` | `old_1_5/bench-diag/` | État BDD debug |
| `scripts/_check_today.py` | `old_1_5/bench-diag/` | Vérif données du jour |
| `scripts/_debug_card.py` | `old_1_5/bench-diag/` | Debug carte |
| `scripts/_debug_card2.py` | `old_1_5/bench-diag/` | Debug carte (suite) |
| `scripts/_debug_guide.py` | `old_1_5/bench-diag/` | Debug guide CM |
| `scripts/audit_phantom_foil.py` | `old_1_5/bench-diag/` | Audit foil fantômes |
| `scripts/remove-kmspico.ps1` | `old_1_5/scripts-oneshot/` | Nettoyage OS one-shot |
| `scripts/remove-unwanted-scheduled-tasks.ps1` | `old_1_5/scripts-oneshot/` | Nettoyage tâches planifiées one-shot |

## Conservé actif (non archivé)

| Chemin | Rôle |
|--------|------|
| `scripts/_bench_market_cold.py` | Bench market movers à froid (régression perf) |
| `scripts/_diag_verify_migration.py` | Diagnostic `verify_migration` post-migration |
| `scripts/migrate_price_daily.py` | Migration / dry-run |
| `scripts/remigrate_price_daily.py` | Rebuild `price_daily` depuis legacy |
| `scripts/health_check_daily.py` | Santé quotidienne |
| `scripts/db_validation_suite.py` | Validation 10 cartes avant/après |
| `mtg_pwa/price_daily.py` | Modèle compact + vue compat |

## `price_snapshots_legacy` — procédure archivage BDD (manuel, post-validation)

**État validé (2026-07-10) :** `verify_migration.match: true`, intégrité OK, BDD ~5,62 Go.

La table `price_snapshots_legacy` reste dans `data/mtg_pwa.sqlite3` tant que l'export n'est pas confirmé. **Ne pas DROP.**

### Étapes recommandées (Guillaume)

1. Vérifier backup récent : `python weekly_backup.py --status`
2. Export optionnel vers backup cumulatif :
   ```bash
   python scripts/db_audit.py
   # ATTACH + INSERT OR IGNORE vers E:\Backup\MTG Data\mtg_cumulative.sqlite3
   # (déjà couvert par weekly_backup pour les tables incrémentielles)
   ```
3. Après 7+ jours d'usage stable sans legacy lu :
   - Documenter date de retrait dans ce manifeste
   - Option future : `ALTER TABLE price_snapshots_legacy RENAME TO ...` hors chemin actif ou split ATTACH — **jamais DELETE**
4. `VACUUM` post-archivage pour récupérer l'espace disque

## Hygiène post-clôture

- [x] Push `main` (B 1.4→1.5)
- [x] Move benches/debug → `old_1_5/`
- [ ] DEV_LOG sections X=56–65 → Historique (avant MEP)
- [ ] `project-state.md` à jour
- [ ] Gate MEP (A) : `npm run version:mep -- --dry-run` sur go explicite

## Références

- [`docs/DATABASE_ARCHITECTURE.md`](DATABASE_ARCHITECTURE.md)
- [`CLEANUP_0_1_MANIFEST.md`](CLEANUP_0_1_MANIFEST.md)
- REFERENCE [`fin-de-B-cleanup.md`](C:/Dev/Project/REFERENCE/docs/processes/fin-de-B-cleanup.md)
