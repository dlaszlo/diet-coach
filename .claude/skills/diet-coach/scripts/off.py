#!/usr/bin/env python3
"""Open Food Facts nutrition lookup — an optional, network-dependent helper.

Kept separate from track.py because it is the only part that talks to the
outside world (HTTP), with its own failure modes; the rest of the tool only
edits local markdown. Stdlib only. The caller is responsible for catching
network exceptions (urllib.error.URLError, socket.timeout, …).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

_UA = "health-tracker/1.0 (personal meal log)"
_FIELDS = "code,product_name,brands,quantity,serving_size,nutriments"


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def off_product(barcode: str) -> dict | None:
    """Look up a single product by barcode (None if not found)."""
    url = (f"https://world.openfoodfacts.org/api/v2/product/"
           f"{urllib.parse.quote(barcode)}.json?fields={_FIELDS}")
    data = _get(url)
    return data.get("product") if data.get("status") == 1 else None


def off_search(query: str, n: int) -> list[dict]:
    """Free-text product search (most relevant first, up to n hits)."""
    url = "https://world.openfoodfacts.org/cgi/search.pl?" + urllib.parse.urlencode(
        {"search_terms": query, "search_simple": 1, "action": "process",
         "json": 1, "page_size": n, "fields": _FIELDS})
    return _get(url).get("products", [])


# --- nutriment accessors (None when the product lacks that datum) ----------- #
def _nutriment(p: dict, key: str) -> float | None:
    v = p.get("nutriments", {}).get(key)
    return float(v) if isinstance(v, (int, float)) else None


def energy_100g(p: dict) -> float | None:
    return _nutriment(p, "energy-kcal_100g")


def protein_100g(p: dict) -> float | None:
    return _nutriment(p, "proteins_100g")


def fat_100g(p: dict) -> float | None:
    return _nutriment(p, "fat_100g")


# --- formatting ------------------------------------------------------------- #
def _fmt(p: dict, key: str, unit: str = "") -> str:
    v = _nutriment(p, key)
    return f"{v:g}{unit}" if v is not None else "n/a"


def product_label(p: dict) -> str:
    name = p.get("product_name") or "(unnamed)"
    brand = (p.get("brands") or "").split(",")[0].strip()
    return f"{name} — {brand}" if brand else name


def fmt_product(p: dict) -> str:
    lines = [product_label(p)]
    if p.get("code"):
        lines.append(f"  barcode: {p['code']}")
    if p.get("quantity"):
        lines.append(f"  pack size: {p['quantity']}")
    lines.append(
        f"  per 100 g: {_fmt(p, 'energy-kcal_100g')} kcal | "
        f"protein {_fmt(p, 'proteins_100g', 'g')} | fat {_fmt(p, 'fat_100g', 'g')} | "
        f"carbs {_fmt(p, 'carbohydrates_100g', 'g')} | fiber {_fmt(p, 'fiber_100g', 'g')} | "
        f"salt {_fmt(p, 'salt_100g', 'g')}")
    return "\n".join(lines)


def fmt_portion(p: dict, grams: float) -> str | None:
    """One-line preview of the kcal for the given grams (None if no data)."""
    e100 = energy_100g(p)
    if e100 is None:
        return None
    kcal = round(e100 * grams / 100)
    prot = protein_100g(p)
    extra = f", protein {prot * grams / 100:.0f} g" if prot is not None else ""
    return f"  → {grams:g} g portion: ~{kcal} kcal{extra}"
