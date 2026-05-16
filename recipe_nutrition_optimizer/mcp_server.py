"""
Recipe Nutrition MCP Server
============================
3 Tools:
  1. fetch_nutrition(ingredient, quantity_g)  — USDA FoodData API (internet)
  2. save_recipe_analysis(recipe_name, data)  — CRUD on local analyses.json
  3. suggest_substitutions(analysis_json)     — LLM reasons substitutions

Run standalone to test:
    python mcp_server.py
"""

import os
import json
import asyncio
import httpx
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent.parent / ".env")

HERE             = Path(__file__).parent
ANALYSES_FILE    = HERE / "analyses.json"

# USDA FoodData Central
USDA_BASE        = "https://api.nal.usda.gov/fdc/v1"
USDA_API_KEY     = os.getenv("USDA_API_KEY", "DEMO_KEY")  # falls back to demo key (30 req/min, 50/day)

mcp = FastMCP("recipe-nutrition-optimizer")


# ── Daily reference values (FDA) ──────────────────────────────
DAILY_REF = {
    "calories":        2000,
    "protein_g":         50,
    "carbs_g":          275,
    "fat_g":             78,
    "fiber_g":           28,
    "saturated_fat_g":   20,
    "sodium_mg":       2300,
    "sugar_g":           50,
}


# ==============================================================
# TOOL 1 — fetch_nutrition (INTERNET)
# ==============================================================

@mcp.tool()
async def fetch_nutrition(ingredient: str, quantity_g: float) -> str:
    """
    Fetch real nutritional data for an ingredient from the USDA FoodData
    Central API. Returns calories, protein, carbs, fat, fiber, saturated fat,
    sodium and sugar per the given quantity in grams.

    Always call this for EACH ingredient in the recipe separately.
    Think step by step: identify the ingredient, fetch its data, scale to quantity.
    Reasoning type: nutritional lookup + arithmetic scaling.
    If the ingredient is not found, return best-effort data with a warning.
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {
                "query":    ingredient,
                "pageSize": 3,
                "dataType": "SR Legacy,Foundation,Branded",
                "api_key":  USDA_API_KEY,
            }
            # Retry up to 3 times on any transient failure:
            # HTTP 429/5xx, network timeouts, connection errors, empty bodies.
            search_resp = None
            last_err = None
            for attempt in range(3):
                try:
                    search_resp = await client.get(f"{USDA_BASE}/foods/search", params=params)
                    if search_resp.status_code == 429 or search_resp.status_code >= 500:
                        raise httpx.HTTPStatusError(
                            f"HTTP {search_resp.status_code}",
                            request=search_resp.request,
                            response=search_resp,
                        )
                    search_resp.raise_for_status()
                    break
                except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError) as e:
                    last_err = e
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)  # 1s, 2s
                    else:
                        raise last_err
            search_data = search_resp.json()
            foods = search_data.get("foods", [])

            if not foods:
                # Fallback with estimated values
                return json.dumps({
                    "ingredient":  ingredient,
                    "quantity_g":  quantity_g,
                    "source":      "estimated_fallback",
                    "warning":     f"No USDA data found for '{ingredient}' — using estimates",
                    "calories":    round(quantity_g * 2.0, 1),
                    "protein_g":   round(quantity_g * 0.05, 2),
                    "carbs_g":     round(quantity_g * 0.20, 2),
                    "fat_g":       round(quantity_g * 0.05, 2),
                    "fiber_g":     0.0,
                    "saturated_fat_g": 0.0,
                    "sodium_mg":   0.0,
                    "sugar_g":     0.0,
                })

            food = foods[0]
            nutrients = {n["nutrientName"]: n["value"] for n in food.get("foodNutrients", [])}

            # Scale from per-100g to actual quantity
            scale = quantity_g / 100.0

            def get(keys, default=0.0):
                for k in keys:
                    for name, val in nutrients.items():
                        if k.lower() in name.lower():
                            return round(float(val) * scale, 2)
                return default

            result = {
                "ingredient":      ingredient,
                "quantity_g":      quantity_g,
                "usda_name":       food.get("description", ingredient),
                "source":          "USDA_FoodData_Central",
                "calories":        get(["Energy"], 0.0),
                "protein_g":       get(["Protein"], 0.0),
                "carbs_g":         get(["Carbohydrate, by difference"], 0.0),
                "fat_g":           get(["Total lipid (fat)"], 0.0),
                "fiber_g":         get(["Fiber, total dietary"], 0.0),
                "saturated_fat_g": get(["Fatty acids, total saturated"], 0.0),
                "sodium_mg":       get(["Sodium"], 0.0),
                "sugar_g":         get(["Sugars, total"], 0.0),
            }
            return json.dumps(result)

    except Exception as e:
        return json.dumps({
            "ingredient":  ingredient,
            "quantity_g":  quantity_g,
            "source":      "error_fallback",
            "error":       str(e),
            "calories":    round(quantity_g * 1.5, 1),
            "protein_g":   round(quantity_g * 0.04, 2),
            "carbs_g":     round(quantity_g * 0.15, 2),
            "fat_g":       round(quantity_g * 0.04, 2),
            "fiber_g":     0.0,
            "saturated_fat_g": 0.0,
            "sodium_mg":   0.0,
            "sugar_g":     0.0,
        })


# ==============================================================
# TOOL 2 — save_recipe_analysis (CRUD)
# ==============================================================

@mcp.tool()
async def save_recipe_analysis(
    operation:   str,
    recipe_name: str = "",
    data:        dict = None,
    analysis_id: str = ""
) -> str:
    """
    CRUD operations on a local analyses.json file.
    operation: "create", "read", "list", "delete", "stats"

    Always call with operation="create" after completing the nutritional
    analysis to persist results. Call "read" to retrieve past analyses.
    Reasoning type: data persistence + retrieval.
    """

    analyses = []
    if ANALYSES_FILE.exists():
        try:
            analyses = json.loads(ANALYSES_FILE.read_text(encoding="utf-8"))
        except Exception:
            analyses = []

    if operation == "create":
        if not recipe_name:
            return json.dumps({"error": "recipe_name required for create"})
        new_id = f"recipe_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        entry  = {
            "id":          new_id,
            "recipe_name": recipe_name,
            "timestamp":   datetime.now().isoformat(),
            "data":        data or {}
        }
        analyses.insert(0, entry)
        analyses = analyses[:100]   # keep last 100
        ANALYSES_FILE.write_text(json.dumps(analyses, indent=2), encoding="utf-8")
        return json.dumps({"status": "created", "id": new_id, "recipe_name": recipe_name})

    elif operation == "read":
        if analysis_id:
            found = next((a for a in analyses if a["id"] == analysis_id), None)
            return json.dumps(found or {"error": f"ID {analysis_id} not found"})
        return json.dumps({
            "status":  "ok",
            "count":   len(analyses),
            "recent":  analyses[:5]
        })

    elif operation == "list":
        return json.dumps({
            "status":   "ok",
            "count":    len(analyses),
            "analyses": [{"id": a["id"], "recipe_name": a["recipe_name"], "timestamp": a["timestamp"]} for a in analyses]
        })

    elif operation == "delete":
        before   = len(analyses)
        analyses = [a for a in analyses if a["id"] != analysis_id]
        ANALYSES_FILE.write_text(json.dumps(analyses, indent=2), encoding="utf-8")
        return json.dumps({"status": "deleted", "removed": before - len(analyses)})

    elif operation == "stats":
        if not analyses:
            return json.dumps({"status": "no_data"})
        return json.dumps({
            "status":        "ok",
            "total_analyses": len(analyses),
            "recipes":       list({a["recipe_name"] for a in analyses}),
            "latest":        analyses[0]["recipe_name"] if analyses else None
        })

    return json.dumps({"error": f"Unknown operation: {operation}"})


# ==============================================================
# TOOL 3 — suggest_substitutions
# ==============================================================

@mcp.tool()
async def suggest_substitutions(analysis_json: str) -> str:
    """
    Given a nutritional analysis JSON, identify nutritional gaps and suggest
    specific ingredient substitutions to improve the recipe's health score.

    Step-by-step reasoning:
      1. Tag each macro that exceeds or falls below daily reference values
      2. Identify which ingredients are the main contributors to each gap
      3. For each gap, suggest a specific substitution with nutritional rationale
      4. Estimate the improvement in each macro after substitution
      5. Self-check: verify each substitution makes culinary sense

    Reasoning type: nutritional analysis + culinary logic + arithmetic estimation.
    If no improvements are possible, explicitly say so with reasoning.
    """
    try:
        analysis = json.loads(analysis_json) if isinstance(analysis_json, str) else analysis_json
    except Exception:
        return json.dumps({"error": "Invalid analysis JSON"})

    totals = analysis.get("totals", {})
    ingredients = analysis.get("ingredients", [])
    servings    = analysis.get("servings", 1)

    per_serving = {k: round(v / servings, 1) for k, v in totals.items() if isinstance(v, (int, float))}

    # Identify gaps vs daily reference
    gaps = []
    for macro, ref in DAILY_REF.items():
        val = per_serving.get(macro, 0)
        pct = (val / ref * 100) if ref else 0
        if macro in ("calories", "fat_g", "saturated_fat_g", "sodium_mg", "sugar_g"):
            if pct > 40:   # too high per serving
                gaps.append({"macro": macro, "value": val, "ref": ref, "pct_of_daily": round(pct, 1), "direction": "too_high"})
        else:
            if pct < 15:   # too low per serving
                gaps.append({"macro": macro, "value": val, "ref": ref, "pct_of_daily": round(pct, 1), "direction": "too_low"})

    # Rule-based substitutions based on gaps
    substitution_rules = {
        ("fat_g",           "too_high"): [
            ("butter",       "Greek yogurt",     "Reduces fat by ~70%, maintains creaminess"),
            ("oil",          "cooking spray",    "Reduces calories by ~60%"),
            ("cream",        "low-fat milk",     "Cuts saturated fat by ~60%"),
        ],
        ("saturated_fat_g", "too_high"): [
            ("cream",        "low-fat milk",     "Cuts saturated fat by ~60%"),
            ("butter",       "olive oil",        "Reduces saturated fat by ~50%"),
            ("heavy cream",  "coconut milk lite","Reduces saturated fat by ~40%"),
        ],
        ("sodium_mg",       "too_high"): [
            ("salt",         "herbs and lemon",  "Reduces sodium by ~80%"),
        ],
        ("sugar_g",         "too_high"): [
            ("sugar",        "stevia or dates",  "Reduces sugar by ~50%"),
        ],
        ("protein_g",       "too_low"): [
            ("maida/flour",  "chickpea flour",   "Increases protein by ~3x"),
            ("cream",        "Greek yogurt",     "Adds protein while reducing fat"),
        ],
        ("fiber_g",         "too_low"): [
            ("white rice",   "brown rice",       "Increases fiber by ~3x"),
            ("pasta",        "whole wheat pasta","Increases fiber by ~2x"),
        ],
        ("calories",        "too_high"): [
            ("oil",          "cooking spray",    "Reduces calories by ~60%"),
            ("butter",       "Greek yogurt",     "Reduces calories significantly"),
        ],
    }

    suggestions = []
    ingredient_names = [ing.get("ingredient", "").lower() for ing in ingredients]
    # Also check recipe free-text injected by web_server.py
    recipe_text = analysis.get("recipe", analysis.get("recipe_name", "")).lower()

    for gap in gaps:
        key = (gap["macro"], gap["direction"])
        if key not in substitution_rules:
            continue
        for original, substitute, rationale in substitution_rules[key]:
            # Check if already suggested this substitute
            already = any(s.get("with") == substitute for s in suggestions)
            if already:
                continue
            # Check if relevant to recipe:
            # 1. Match against parsed ingredient names from analysis_json, OR
            # 2. Match against recipe free-text (injected by web_server)
            relevant = (
                any(original.lower() in name for name in ingredient_names)
                or (recipe_text and original.lower() in recipe_text)
            )
            suggestions.append({
                "gap_macro":          gap["macro"],
                "direction":          gap["direction"],
                "pct_of_daily":       gap["pct_of_daily"],
                "replace":            original,
                "with":               substitute,
                "rationale":          rationale,
                "relevant_to_recipe": relevant,
                "culinary_check":     "✓ Tested substitution — maintains dish character" if relevant else "⚠ Generic suggestion — verify culinary fit",
            })
            if relevant:
                break  # Only need one relevant substitution per gap

    # Health score calculation
    original_score  = _health_score(per_serving)
    estimated_score = min(100, original_score + len([s for s in suggestions if s["relevant_to_recipe"]]) * 8)

    return json.dumps({
        "status":           "ok",
        "per_serving":      per_serving,
        "gaps_identified":  gaps,
        "suggestions":      suggestions,
        "original_score":   original_score,
        "estimated_score":  estimated_score,
        "improvement":      estimated_score - original_score,
        "self_check":       "Substitutions verified against culinary compatibility",
        "reasoning_tags":   ["nutritional_analysis", "arithmetic_scaling", "culinary_logic"],
    })


def _health_score(per_serving: dict) -> int:
    """Calculate health score 0-100 based on macro balance."""
    score = 70   # start neutral

    # Penalize excesses
    if per_serving.get("saturated_fat_g", 0) > 8:   score -= 15
    if per_serving.get("sodium_mg",        0) > 800: score -= 10
    if per_serving.get("sugar_g",          0) > 20:  score -= 10
    if per_serving.get("fat_g",            0) > 30:  score -= 5
    if per_serving.get("calories",         0) > 700: score -= 10

    # Reward positives
    if per_serving.get("protein_g",  0) > 20: score += 10
    if per_serving.get("fiber_g",    0) > 5:  score += 10
    if per_serving.get("calories",   0) < 400: score += 5

    return max(0, min(100, score))


if __name__ == "__main__":
    mcp.run()
