# Warframe Market Syndicate Mod Seller

A Python automation tool that manages sell orders on [Warframe Market](https://warframe.market) for syndicate mods. It checks live market prices, creates or updates listings when prices are profitable, and removes listings when the market drops below a configurable minimum.

---

## What it does

Selling syndicate mods on Warframe Market manually is repetitive: you have to look up each mod's current price, decide if it's worth listing, and either create, update, or remove your order. With dozens of mods across multiple syndicates, this becomes tedious.

This script automates the entire workflow:

- Fetches the current lowest sell price for each mod in real time
- Sets your listing price to **lowest market price + 1p** (competitive without racing to the bottom)
- Creates a new order if you don't have one yet
- Updates an existing order if the price has changed
- Deletes your order if the market price has dropped below your minimum
- Falls back to a configurable default price if no active sellers exist

---

## Features

- JWT-based authentication (no password stored)
- Per-syndicate or all-syndicates processing
- Bulk delete orders when you lose syndicate standing
- Configurable minimum price, quantity, rank, and fallback price
- Rate limiting to respect the API
- Dual output: terminal + persistent log file (`warframe_seller.log`)

---

## Requirements

- Python 3.8+
- `requests` library

```bash
pip install requests
```

---

## Security Notice

> ⚠️ **Your JWT token is a sensitive credential.** Treat it like a password.
>
> - **Never commit `config.json` with a real token to a public repository.** Add `config.json` to your `.gitignore` to prevent accidental exposure.
> - If you accidentally push your token publicly, log out of Warframe Market immediately to invalidate it, then get a new one.
> - The `config.json` file in this repo contains only a placeholder (`"your_jwt_token_here"`) — fill it in locally and keep it private.

A recommended `.gitignore` entry:

```
config.json
warframe_seller.log
```

## Setup

**1. Clone or download the project files:**

```
warframe_mod_seller.py
config.json
requirements.txt
```

**2. Add your JWT token to `config.json`:**

The script authenticates using your session token from the Warframe Market website.

To get it:
1. Open your browser and log into [warframe.market](https://warframe.market)
2. Press `F12` to open Developer Tools
3. Go to **Application** (Chrome) or **Storage** (Firefox) tab
4. Navigate to **Cookies → https://warframe.market**
5. Find the cookie named `JWT` and copy its value
6. Paste it into `config.json` under `credentials.jwt_token`

> ⚠️ JWT tokens expire. If you get authentication errors, repeat this process to get a fresh token.

**3. Set your platform:**

Change `"platform"` in `config.json` to match where you play (`pc`, `ps4`, `xbox`, `switch`, or `mobile`). This determines which platform's market your orders are listed on.

---

## Configuration

All settings live in `config.json`:

```json
{
    "credentials": {
        "jwt_token": "your_token_here",
        "platform": "ps4"
    },
    "settings": {
        "min_platinum": 14,
        "quantity": 1,
        "rank": 0,
        "fallback_price": 15
    },
    "syndicates": {
        "New Loka": ["Abating Link", "Jet Stream", "..."],
        "The Perrin Sequence": ["Greedy Pull", "Despoil", "..."]
    }
}
```

| Setting | Description |
|---|---|
| `min_platinum` | Minimum price to bother listing. Orders below this are deleted. |
| `quantity` | How many copies to list per order. |
| `rank` | Mod rank (0 = unranked). |
| `fallback_price` | Price to use when no active sellers exist on the market. |

To add mods to a syndicate, just add their names to the list in `syndicates`. The name must match the in-game mod name exactly.

---

## Usage

**Process a specific syndicate** (recommended — run one at a time since standing is gained separately per syndicate):

```bash
python warframe_mod_seller.py --list "New Loka"
```

**Process all syndicates at once:**

```bash
python warframe_mod_seller.py --list-all
```

**Delete all orders for a syndicate** (useful when you lose standing and can no longer restock):

```bash
python warframe_mod_seller.py --delete "New Loka"
```

**Delete all syndicate orders across all syndicates:**

```bash
python warframe_mod_seller.py --delete-all
```

---

## How the pricing works

For each mod, the script fetches the current top sell orders and finds the lowest active in-game price. It then sets your price to **lowest + 1p**.

For example, if the cheapest seller is at 13p, your order is set to 14p. This keeps you competitive in the queue without aggressively undercutting — once the 13p seller sells, yours becomes the new lowest.

If the resulting price is below `min_platinum`, the order is removed rather than listed at a loss.

If there are no active sellers at all, the script uses `fallback_price` from config.

---

## Output

Each run prints a live log to the terminal and appends to `warframe_seller.log` in the same folder.

At the end of each run a summary is printed:

```
============================================================
SUMMARY
============================================================
➕ Created  : 3
🔄 Updated  : 12
❌ Deleted  : 5
⚠️  Skipped  : 8
⛔ Errors   : 1
```

---

## Project structure

```
warframe_mod_seller.py   # Main script
config.json              # Your credentials, settings, and mod lists
requirements.txt         # Python dependencies
warframe_seller.log      # Auto-generated run log (created on first run)
```

The code is split into two classes:

- **`WarframeMarketClient`** — handles all HTTP communication with the API (GET, POST, PATCH, DELETE), authentication, and rate limiting.
- **`SyndicateModManager`** — contains the business logic: price decisions, order creation/update/deletion, and the delete-by-syndicate workflows.

---

## Notes

- This tool only manages **sell orders**. It does not place buy orders.
- The Warframe Market API is unofficial and may change without notice.
- Mod names in `config.json` must match the exact in-game names.
- Running the script too frequently may result in temporary rate limiting from the API.
