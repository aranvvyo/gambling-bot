# Visual asset inventory

No AI image-generation tool was available for this phase. The project retains its bundled original, code-drawn PNG illustrations generated with `assets/generate_visual_assets.py`; no external image URL is required. The source script can regenerate the pack. Phase 5 adds no new raster assets.

| Asset | Dimensions | Intended use |
|---|---:|---|
| `logo.png` | 256 × 256 | Emerald Vault mark |
| `welcome.png` | 1200 × 400 | Casino lobby banner |
| `games.png` | 1200 × 400 | Prefix game menu |
| `wallet.png` | 1200 × 400 | Wallet and private deposit menu |
| `mines.png` | 256 × 256 | Mines result thumbnail |
| `blackjack.png` | 256 × 256 | Blackjack result thumbnail |
| `dragon-tower.png` | 256 × 256 | Dragon Tower result thumbnail |
| `crash.png` | 256 × 256 | Crash result thumbnail |
| `limbo.png` | 256 × 256 | Limbo result thumbnail |
| `dice.png` | 256 × 256 | Dice result thumbnail |
| `chicken-road.png` | 256 × 256 | Chicken Road result thumbnail |
| `limo.png` | 256 × 256 | Limo result thumbnail |
| `pump.png` | 256 × 256 | Pump result thumbnail |

The visuals use charcoal, emerald and muted gold. They are decorative only; no image is presented as a payment QR or transaction confirmation. Deposit QR codes are generated at runtime from the invoice address returned by Apirone.

## Settlement result images

`services/result_art.py` draws an in-memory 960×480 PNG per settled game using only Python's standard library. The result graphic is generated from the settled callback values and attached as `game-result.png`; no external URLs, missing bundled files, placeholder QR codes, or extra image dependencies are used.

- Limbo, Crash, and Pump: plotted multiplier curve, labeled actual result and target/crash point; Limbo includes its target threshold line.
- Mines: settled tile map with revealed safe picks and actual mines.
- Dragon Tower: row progression, actual safe path, selected path, and multiplier.
- Blackjack: actual player/dealer cards.
- Dice: actual roll and direction/target.
- Chicken Road: actual safe path and selected progression.
- Limo: selected car and actual limousine position.

Coinflip is not included in this inventory because this project has no Coinflip command or game implementation.


Phase 5 player-home and admin-dashboard UI use the existing shared embed theme, custom-emoji fallbacks, bundled branding art, and dynamic game-result renderers. The daily reward, leaderboard, dashboard, and deposit status panels use actual database/provider results; no decorative image represents a payment.
