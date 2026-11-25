# de-zep-feed

Een feed voor een ESP32-sportscherm (kerstcadeau 2026).

GitHub haalt elk kwartier alle bronnen op en publiceert één klein bestand,
`feed.json`, via GitHub Pages. Het scherm leest alleen dat bestand.

## Wat staat waar

| Bestand | Wat het doet |
|---|---|
| `bronnen.yaml` | Lijst met bronnen. Nieuwe RSS-feed: blokje kopiëren. Uitzetten: `aan: false`. |
| `uitspraken.csv` | Uitspraken van de dag (tekst, wie, foto). |
| `bouw_feed.py` | Haalt alles op en schrijft `site/feed.json`. |
| `site/index.html` | Preview van het scherm. Toont de live feed. |
| `.github/workflows/bouw-feed.yml` | Draait elk kwartier, na elke wijziging, of met de knop "Run workflow". |

## Adressen

- Preview: https://isa-claude-17.github.io/de-zep-feed/
- Feed voor het scherm: https://isa-claude-17.github.io/de-zep-feed/feed.json
