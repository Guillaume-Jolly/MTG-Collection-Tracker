# MTG Collection Tracker

PWA mobile-first pour gérer une collection Magic: The Gathering : recherche Scryfall, suivi des prix EUR, historique local et import de decks preconstruits MTGJSON.

**Dépôt :** [github.com/Guillaume-Jolly/MTG-Collection-Tracker](https://github.com/Guillaume-Jolly/MTG-Collection-Tracker)

## Installation

```bash
git clone https://github.com/Guillaume-Jolly/MTG-Collection-Tracker.git
cd MTG-Collection-Tracker
```

## Fonctionnalités

- Recherche d'impressions via Scryfall (filtre langue, versions serialized)
- Collection locale avec quantités par finition (`nonfoil`, `foil`, `etched`)
- Estimation de valeur en EUR et snapshots de prix
- Courbes d'historique par carte/finition
- Fiche carte (rulings, variations 1j / 1m / 6m / 1a / 5a)
- Recherche et import de decks Commander MTGJSON

## Lancement local

### Windows

```powershell
python run_mvp.py --host 0.0.0.0 --port 8000
```

Ou double-cliquer / exécuter `start_mvp.bat`.

### Linux / macOS

```bash
./start_mvp.sh
```

Puis ouvrir [http://localhost:8000](http://localhost:8000).

Sur téléphone, utiliser l'adresse IP locale de la machine (ex. `http://192.168.x.x:8000`) et « Ajouter à l'écran d'accueil » pour installer la PWA.

## Stockage

Par défaut, SQLite stocke les données dans :

```text
data/mtg_pwa.sqlite3
```

Chemin personnalisable :

```bash
set MTG_PWA_DB=C:\chemin\vers\mtg.sqlite3
python run_mvp.py
```

## Tests

```bash
python -m unittest discover -s tests
```

## Versionnement (agents Cursor)

Label UI : `v{semver}.{XX}` ou `v{semver}.{XX}.{Y}` (ex. `v1.1.0.02.1`).

- **Hooks** : `.cursor/hooks.json` (X auto à chaque message user, Y auto en fin de tour si diff)
- **Journal** : `docs/traceability/changelog/DEV_LOG_0_1.md`
- **Doc** : [`docs/agent-guide/05-politique-versionnement.md`](docs/agent-guide/05-politique-versionnement.md) · [`AGENTS.md`](AGENTS.md)

Commandes (nécessite [Node.js](https://nodejs.org/) pour les scripts) :

```bash
npm run version:prompt   # X+1 (normalement via hook)
npm run version:task     # Y+1
npm run version:sync     # sync build-info sans bump
```

Redémarrer Cursor après installation des hooks.

## Dépendances

Python 3.11+ (stdlib uniquement). Node.js 18+ recommandé pour le versionnement X/Y et les hooks Cursor.

## Contribution

Issues, pull requests et discussions : [MTG-Collection-Tracker sur GitHub](https://github.com/Guillaume-Jolly/MTG-Collection-Tracker).
