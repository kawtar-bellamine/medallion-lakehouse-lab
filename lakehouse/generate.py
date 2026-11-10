"""Synthetic but realistic sources for a fictional Swiss omnichannel watch brand ("Horlogerie Alpina").

Three systems deliver one file each per day, as they would land in a data lake:
    erp/orders_YYYY-MM-DD.csv      order lines from the ERP (stores and web shop)
    web/events_YYYY-MM-DD.jsonl    web analytics events
    ref/products.csv               product catalogue (once)
Known defects are injected and counted, so the quality checks of the Silver layer can be scored.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import random
from pathlib import Path

START = dt.date(2026, 9, 1)
CHANNELS = ["web_ch", "web_eu", "store_geneve", "store_lausanne", "store_zurich"]
CATEGORIES = {"watch": (390, 2900), "strap": (49, 190), "service": (80, 450), "accessory": (25, 160)}
FIRST = ["Lea", "Noah", "Mia", "Luca", "Emma", "Elias", "Sofia", "Louis", "Lina", "Leon", "Chloe", "Matteo"]
LAST = ["Muller", "Meier", "Schmid", "Keller", "Weber", "Rochat", "Favre", "Rossi", "Bianchi", "Huber"]


def products(rng: random.Random) -> list[dict]:
    out = []
    for i in range(1, 121):
        cat = rng.choices(list(CATEGORIES), [0.35, 0.3, 0.15, 0.2])[0]
        lo, hi = CATEGORIES[cat]
        out.append({"product_code": f"HA-{cat[:2].upper()}-{i:04d}", "category": cat,
                    "name_fr": f"{cat.capitalize()} modèle {i}", "name_de": f"{cat.capitalize()} Modell {i}",
                    "list_price_chf": round(rng.uniform(lo, hi), 0), "launch_year": rng.choice([2022, 2023, 2024, 2025])})
    return out


def write_sources(root: Path, days: int = 60, seed: int = 7) -> dict:
    """Writes the landing zone and returns the count of every injected defect (the answer key)."""
    rng = random.Random(seed)
    land = root / "landing"
    for sub in ("erp", "web", "ref"):
        (land / sub).mkdir(parents=True, exist_ok=True)
    prods = products(rng)
    with open(land / "ref" / "products.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(prods[0]))
        w.writeheader(); w.writerows(prods)
    customers = [{"id": f"C{i:05d}", "email": f"{rng.choice(FIRST).lower()}.{rng.choice(LAST).lower()}{i}@mail.ch"}
                 for i in range(1, 4001)]
    defects = {"duplicate_line": 0, "missing_customer": 0, "zero_quantity": 0, "price_in_cents": 0,
               "unknown_product": 0, "swiss_date_format": 0, "late_arrival": 0}
    order_no, late_buffer = 100000, []
    cols = ["order_id", "line_no", "order_ts", "channel", "customer_id", "customer_email", "product_code",
            "quantity", "unit_price", "currency", "status"]
    for d in range(days):
        day = START + dt.timedelta(days=d)
        weekend = day.weekday() >= 5
        rows = list(late_buffer)
        late_buffer = []
        n_orders = int(rng.gauss(260 if weekend else 200, 25))
        for _ in range(n_orders):
            order_no += 1
            ch = rng.choices(CHANNELS, [0.35, 0.15, 0.2, 0.15, 0.15])[0]
            cust = rng.choice(customers)
            ts = dt.datetime.combine(day, dt.time(rng.randint(8, 21), rng.randint(0, 59), rng.randint(0, 59)))
            cur = "EUR" if ch == "web_eu" else "CHF"
            status = rng.choices(["completed", "returned", "cancelled"], [0.9, 0.07, 0.03])[0]
            for ln in range(1, rng.choice([1, 1, 1, 2, 2, 3]) + 1):
                p = rng.choice(prods)
                price = p["list_price_chf"] * (0.94 if cur == "EUR" else 1.0) * rng.choice([1, 1, 1, 0.9, 0.8])
                row = {"order_id": f"O{order_no}", "line_no": ln, "order_ts": ts.isoformat(sep=" "), "channel": ch,
                       "customer_id": cust["id"], "customer_email": cust["email"], "product_code": p["product_code"],
                       "quantity": rng.choice([1, 1, 1, 1, 2]), "unit_price": round(price, 2), "currency": cur,
                       "status": status}
                r = rng.random()
                if r < 0.005:
                    row["customer_id"] = ""; defects["missing_customer"] += 1
                elif r < 0.008:
                    row["quantity"] = 0; defects["zero_quantity"] += 1
                elif r < 0.010:
                    row["unit_price"] = round(row["unit_price"] * 100); defects["price_in_cents"] += 1
                elif r < 0.014:
                    row["product_code"] = row["product_code"].replace("HA-", "HX-"); defects["unknown_product"] += 1
                if ch.startswith("store") and rng.random() < 0.3:      # store tills export Swiss dates
                    row["order_ts"] = ts.strftime("%d.%m.%Y %H:%M:%S"); defects["swiss_date_format"] += 1
                if rng.random() < 0.01 and d < days - 1:              # arrives with the next day's file
                    late_buffer.append(row); defects["late_arrival"] += 1
                    continue
                rows.append(row)
                if rng.random() < 0.015:                               # resent by the interface
                    rows.append(dict(row)); defects["duplicate_line"] += 1
        with open(land / "erp" / f"orders_{day}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader(); w.writerows(rows)
        with open(land / "web" / f"events_{day}.jsonl", "w", encoding="utf-8") as f:
            for _ in range(int(n_orders * 14)):
                ts = dt.datetime.combine(day, dt.time(rng.randint(0, 23), rng.randint(0, 59)))
                ev = rng.choices(["page_view", "product_view", "add_to_cart", "checkout"], [0.55, 0.3, 0.1, 0.05])[0]
                f.write(json.dumps({"ts": ts.isoformat(), "session": hashlib.md5(f"{d}-{rng.random()}".encode())
                                    .hexdigest()[:12], "event": ev, "product_code": rng.choice(prods)["product_code"],
                                    "market": rng.choice(["CH", "CH", "CH", "EU"])}) + "\n")
    return defects
