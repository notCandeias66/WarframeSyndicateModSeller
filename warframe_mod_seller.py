#!/usr/bin/env python3
"""
Warframe Market Syndicate Mod Seller
Automates listing syndicate mods based on market prices using JWT authentication.
"""

import requests
import json
import time
import argparse
import logging
from typing import List, Dict, Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging setup — writes to both terminal and warframe_seller.log
# ---------------------------------------------------------------------------

def setup_logging():
    log_format = "%(asctime)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt="%Y-%m-%d %H:%M",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("warframe_seller.log", encoding="utf-8"),
        ],
    )

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API client
# ---------------------------------------------------------------------------

class WarframeMarketClient:
    """Low-level client for the Warframe Market v2 API."""

    BASE_URL = "https://api.warframe.market/v2"
    RATE_LIMIT_DELAY = 0.35  # seconds between requests

    def __init__(self, jwt_token: str, platform: str = "ps4"):
        self.session = requests.Session()
        self.session.headers.update({
            "Platform": platform,
            "Language": "en",
            "Content-Type": "application/json",
            "Authorization": f"JWT {jwt_token}",
            "User-Agent": "Mozilla/5.0"
        })
        self.session.cookies.set("JWT", jwt_token, domain="api.warframe.market")
        log.info("✅ Client initialized with JWT token (platform: %s)", platform)

    def _get(self, path: str) -> Optional[Dict]:
        try:
            r = self.session.get(f"{self.BASE_URL}{path}")
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                logging.warning("⛔ GET %s failed: %s", path, e)
            return None
        except requests.exceptions.RequestException as e:
            log.warning("⛔ GET %s failed: %s", path, e)
            return None
        
    def _post(self, path: str, payload: Dict) -> bool:
        try:
            r = self.session.post(f"{self.BASE_URL}{path}", json=payload)
            r.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            log.warning("⛔ POST %s failed: %s", path, e)
            return False
        
    def _patch(self, path: str, payload: Dict) -> bool:
        try:
            r = self.session.patch(f"{self.BASE_URL}{path}", json=payload)
            r.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            log.warning("⛔ PATCH %s failed: %s", path, e)
            return False
        
    def _delete(self, path: str) -> bool:
        try:
            r = self.session.delete(f"{self.BASE_URL}{path}")
            r.raise_for_status()
            return True
        except requests.exceptions.RequestException as e:
            log.warning("⛔ DELETE %s failed: %s", path, e)
            return False
        
    def delay(self):
        time.sleep(self.RATE_LIMIT_DELAY)

    # --- Public API methods -------------------------------------------------

    def get_item_info(self, mod_name: str) -> Optional[Dict]:
        slug = mod_name.lower().replace(" ", "_").replace("'", "")
        return self._get(f"/items/{slug}")
    
    def get_lowest_sell_price(self, url_name: str) -> Optional[Dict]:
        data = self._get(f"/orders/item/{url_name}/top")
        if not data:
            return None
        
        prices = [
            order["platinum"]
            for order in data["data"]["sell"]
            if order["type"] == "sell"
            and order["rank"] == 0
            and order["user"]["status"] == "ingame"
        ]
        return min(prices) if prices else None
    
    def get_my_orders(self) -> List[Dict]:
        data = self._get("/orders/my")
        return data["data"] if data else []
    
    def create_order(self, item_id: str, platinum: int, quantity: int, rank: int) -> bool:
        return self._post("/order", {
            "itemId": item_id,
            "type": "sell",
            "platinum": platinum,
            "quantity": quantity,
            "visible": True,
            "rank": rank,
        })
    
    def update_order(self, order_id: str, platinum: int, quantity: int, rank: int) -> bool:
        return self._patch(f"/order/{order_id}", {
            "platinum": platinum,
            "quantity": quantity,
            "visible": True,
            "rank": rank,
        })
    
    def delete_order(self, order_id: str) -> bool:
        return self._delete(f"/order/{order_id}")
    
# ---------------------------------------------------------------------------
# Syndicate mod manager
# ---------------------------------------------------------------------------

class SyndicateModManager:
    """Handles the business logic for listing / updating / deleting mod orders."""

    def __init__(self, client: WarframeMarketClient, config: Dict):
        self.client = client
        self.config = config
        settings = config["settings"]
        self.min_platinum: int = settings["min_platinum"]
        self.quantity: int = settings["quantity"]
        self.rank: int = settings["rank"]
        self.fallback_price: int = settings.get("fallback_price", 15)

    def _build_order_id_map(self, orders: List[Dict]) -> Dict[str, Dict]:
        """Return {itemId: order} — no API calls needed, itemId is on every order."""
        return {order["itemId"]: order for order in orders if "itemId" in order}
    
    def _compute_target_price(self, lowest: int) -> int:
        """Price strategy: lowest + 1p (competitive without undercutting too hard)."""
        return lowest + 1
    
    def _handle_good_price(self, mod_name: str, item_id: str, target_price: int, existing_order: Optional[Dict], results: Dict):
        """Create or update an order when price meets the minimum."""

        if existing_order:
            old_price = existing_order["platinum"]
            if old_price == target_price and existing_order.get("visible"):
                log.info("[i] Already listed at %dp — skipping", target_price)
                results["skipped"].append({"mod": mod_name, "reason": "already_optimal", "price": target_price})
                return
            log.info("🔄 Updating: %dp → %dp", old_price, target_price)
            self.client.delay()
            if self.client.update_order(existing_order["id"], target_price, self.quantity, self.rank):
                log.info("✅ Updated")
                results["updated"].append({"mod": mod_name, "old_price": old_price, "new_price": target_price})
            else:
                results["errors"].append({"mod": mod_name, "reason": "update_failed"})
        else:
            log.info("➕ Creating order at %d", target_price)
            self.client.delay()
            if self.client.create_order(item_id, target_price, self.quantity, self.rank):
                log.info("✅ Created")
                results["listed"].append({"mod": mod_name, "price": target_price})
            else:
                results["errors"].append({"mod": mod_name, "reason": "create_failed"})

    def _handle_bad_price(self, mod_name: str, target_price: int, existing_order: Optional[Dict], results: Dict):
        """Delete an existing order when market price is below the minimum."""

        if existing_order:
            log.info("❌ Price too low (%dp) - deleting existing order", target_price)
            self.client.delay()
            if self.client.delete_order(existing_order["id"]):
                log.info("✅ Deleted")
                results["deleted"].append({"mod": mod_name, "reason": "price_too_low", "old_price": existing_order["platinum"], "market_price": target_price,})
            else:
                results["errors"].append({"mod": mod_name, "reason": "delete_failed"})
        else:
            log.info("⚠️ Price too low (%dp) - no order to delete", target_price)
            results["skipped"].append({"mod": mod_name, "reason": "price_too_low", "price": target_price})

    def process_mods(self, mod_names: List[str]) -> Dict:
        """Process a list of mods: create, update, or delete orders as needed."""

        results = {"listed": [], "updated": [], "deleted": [], "skipped": [], "errors": []}

        log.info("\n%s", "=" * 60)
        log.info("Processing %d mods  (min price: %dp)", len(mod_names), self.min_platinum)

        log.info("%s\n", "=" * 60)

        log.info("Fetching your current orders...")
        my_orders = self.client.get_my_orders()
        log.info("Found %d existing orders\n", len(my_orders))

        #orders_by_slug = self._build_order_slug_map(my_orders)
        orders_by_id = self._build_order_id_map(my_orders)

        for i, mod_name in enumerate(mod_names, 1):
            log.info("[%d/%d] %s", i, len(mod_names), mod_name)

            item_info = self.client.get_item_info(mod_name)
            if not item_info:
                log.info("⚠️ Not found on market (may not be tradeable)")
                self.client.delay()
                continue

            url_name = item_info["data"]["slug"]
            item_id = item_info["data"]["id"]
            existing_order = orders_by_id.get(item_id)

            self.client.delay()
            lowest_price = self.client.get_lowest_sell_price(url_name)

            if lowest_price is None:
                # No active sellers — use fallback price
                target_price = self.fallback_price

                log.info("⚠️ No active sellers — using fallback price (%dp)", target_price)
            
            else:
                target_price = self._compute_target_price(lowest_price)
                log.info("  Lowest: %dp → target: %dp", lowest_price, target_price)

            if target_price >= self.min_platinum:
                self._handle_good_price(mod_name, item_id, target_price, existing_order, results)

            else:
                self._handle_bad_price(mod_name, target_price, existing_order, results)

                log.info("")

        return results
        
    def delete_syndicate_orders(self, syndicate_name: str):
        syndicate_mods = self.config["syndicates"].get(syndicate_name)
        if not syndicate_mods:
            log.error("⛔ Syndicate '%s' not found in config.", syndicate_name)
            log.info("Available syndicates: %s", ", ".join(self.config["syndicates"]))
            return
        
        log.info("\n%s", "=" * 60)
        log.info("Deleting orders for: %s", syndicate_name)
        log.info("%s\n", "=" * 60)

        log.info("Resolving item IDs for syndicate mods...")
        syndicate_item_ids = {}
        for mod_name in syndicate_mods:
            info = self.client.get_item_info(mod_name)
            if info:
                syndicate_item_ids[info["data"]["id"]] = mod_name
            self.client.delay()
        log.info("Resolved %d mods\n", len(syndicate_item_ids))

        my_orders = self.client.get_my_orders()
        deleted = 0
 
        for order in my_orders:
            item_id = order.get("itemId")
            if item_id in syndicate_item_ids:
                mod_name = syndicate_item_ids[item_id]
                log.info("❌ Deleting: %s (%dp)", mod_name, order["platinum"])
                if self.client.delete_order(order["id"]):
                    log.info("  ✅ Deleted")
                    deleted += 1
                else:
                    log.warning("  ⛔ Failed to delete")
                self.client.delay()
 
        log.info("\n✅ Deleted %d orders for %s", deleted, syndicate_name)

    def delete_all_syndicate_orders(self):
        log.info("⚠️ Deleting ALL syndicate mod orders\n")
        for syndicate_name in self.config["syndicates"]:
            self.delete_syndicate_orders(syndicate_name)

    def print_summary(self, results: Dict):
        log.info("\n%s", "=" * 60)
        log.info("SUMMARY")
        log.info("%s", "=" * 60)
        log.info("➕ Created: %d", len(results["listed"]))
        log.info("🔄 Updated : %d", len(results["updated"]))
        log.info("❌ Deleted : %d", len(results["deleted"]))
        log.info("⚠️  Skipped : %d", len(results["skipped"]))
        log.info("⛔ Errors  : %d", len(results["errors"]))

        for item in results["listed"]:
            log.info("➕ %s: %dp", item["mod"], item["price"])
        for item in results["updated"]:
            log.info("🔄 %s: %dp → %dp", item["mod"], item["old_price"], item["new_price"])            
        for item in results["deleted"]:
            log.info("❌ %s: was %dp, market %dp", item["mod"], item.get("old_price", "?"), item.get("market_price", "?"))
        for item in results["skipped"]:
            log.info("[i] %s: %s", item["mod"], item["reason"].replace("_", " "))
        for item in results["errors"]:
            log.info("⛔ %s: %s", item["mod"], item.get("reason", "unknown").replace("_", " "))

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
        
def load_config(config_path: str = "config.json") -> Dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with path.open(encoding="utf-8") as f:
        return json.load(f)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Warframe Market Syndicate Mod Seller",
        epilog='Example: python warframe_mod_seller.py --list "New Loka"',
    )
    parser.add_argument("--config", default="config.json", help="Path to config file")
    parser.add_argument("--list", metavar="SYNDICATE", help="Process mods for a specific syndicate")
    parser.add_argument("--list-all", action="store_true", help="Process mods for all syndicates")
    parser.add_argument("--delete", metavar="SYNDICATE", help="Delete all orders for a specific syndicate")
    parser.add_argument("--delete-all", action="store_true", help="Delete all syndicate mod orders")

    args = parser.parse_args()

    config = load_config(args.config)

    jwt_token = config["credentials"].get("jwt_token")
    if not jwt_token:
        log.error("⛔ JWT token missing from config.json — add it under credentials.jwt_token")
        return
    
    platform = config["credentials"].get("platform", "ps4")
    client = WarframeMarketClient(jwt_token, platform)
    manager = SyndicateModManager(client, config)

    if args.delete:
        manager.delete_syndicate_orders(args.delete)
    elif args.delete_all:
        manager.delete_all_syndicate_orders()
    elif args.list:
        mods = config["syndicates"].get(args.list)
        if mods:
            results = manager.process_mods(mods)
            manager.print_summary(results)
        else:
            log.error("⛔ Syndicate '%s' not in config. Available: %s", args.list, ", ".join(config["syndicates"]))
    elif args.list_all:
        all_mods = list(dict.fromkeys(
            mod for mods in config["syndicates"].values() for mod in mods
        ))
        results = manager.process_mods(all_mods)
        manager.print_summary(results)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
