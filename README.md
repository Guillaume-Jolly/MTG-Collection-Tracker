# MTG Collection Tracker

PWA mobile-first pour gérer une collection Magic: The Gathering : recherche Scryfall, suivi des prix EUR, historique local et import de decks preconstruits MTGJSON.

Extrait du projet [mtg_project](https://github.com/Guillaume-Jolly/mtg_project) (branche `cursor/spec-etat-lieux-ed2f`).

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

## Dépendances

Python 3.11+ (stdlib uniquement, pas de packages externes requis).
