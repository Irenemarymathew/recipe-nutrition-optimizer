"""
Recipe Nutrition Optimizer — Web Server (Direct tool calls, no MCP subprocess)
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

load_dotenv()

HERE = Path(__file__).parent
GATEWAY_PATH = HERE.parent / "llm_gateway"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(GATEWAY_PATH))

from client import LLM
print("[startup] LLM imported OK ✓")

# Import tool functions directly — no MCP subprocess needed
from mcp_server import fetch_nutrition, save_recipe_analysis, suggest_substitutions
print("[startup] MCP tools imported OK ✓")

app = FastAPI(title="Recipe Nutrition Optimizer")


class AnalyzeRequest(BaseModel):
    recipe:   str
    servings: int       = 4
    provider: str | None = None


# ── Tool definitions for LLM ───────────────────────────────────
TOOLS = [
    {
        "name": "fetch_nutrition",
        "description": "Fetch real nutritional data for an ingredient from USDA API. Call for each ingredient separately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ingredient": {"type": "string", "description": "Ingredient name e.g. chicken, butter"},
                "quantity_g": {"type": "number", "description": "Quantity in grams"}
            },
            "required": ["ingredient", "quantity_g"]
        }
    },
    {
        "name": "suggest_substitutions",
        "description": "Identify nutritional gaps and suggest healthier ingredient substitutions. Call after all fetch_nutrition calls.",
        "input_schema": {
            "type": "object",
            "properties": {
                "analysis_json": {"type": "string", "description": "JSON string with ingredients and totals"}
            },
            "required": ["analysis_json"]
        }
    },
    {
        "name": "save_recipe_analysis",
        "description": "Save recipe analysis to local file. Use operation=create to save.",
        "input_schema": {
            "type": "object",
            "properties": {
                "operation":   {"type": "string", "enum": ["create", "read", "list", "delete"]},
                "recipe_name": {"type": "string"},
                "data":        {"type": "object"}
            },
            "required": ["operation"]
        }
    }
]


# ── Execute tool by name ───────────────────────────────────────
async def execute_tool(name: str, args: dict, recipe: str = "") -> str:
    try:
        if name == "fetch_nutrition":
            return await fetch_nutrition(**args)

        elif name == "suggest_substitutions":
            # Inject recipe text so relevance check can match against actual ingredients
            try:
                analysis = json.loads(args.get("analysis_json", "{}"))
                if "recipe" not in analysis and recipe:
                    analysis["recipe"] = recipe
                    args = {**args, "analysis_json": json.dumps(analysis)}
            except Exception:
                pass
            return await suggest_substitutions(**args)

        elif name == "save_recipe_analysis":
            # Fix: LLM sometimes nests operation inside data dict
            if "operation" not in args and isinstance(args.get("data"), dict):
                inner = args["data"]
                if "operation" in inner:
                    args = {**inner, "data": inner.get("data")}
            # Fix: ensure operation always present
            if "operation" not in args:
                args["operation"] = "create"
            # Fix: ensure recipe_name for create
            if args.get("operation") == "create" and not args.get("recipe_name"):
                args["recipe_name"] = recipe[:50] if recipe else "Recipe"
            return await save_recipe_analysis(**args)

        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── System prompt ──────────────────────────────────────────────
SYSTEM_PROMPT = """You are a Recipe Nutrition Optimizer Agent. Analyze recipes step by step and suggest healthier alternatives.

REASONING — think before each action:
1. [LOOKUP] Call fetch_nutrition for EACH ingredient with exact name and quantity in grams
2. [ARITHMETIC] After ALL fetches complete, sum up total macros and divide by servings
3. [ANALYSIS] Call suggest_substitutions with full analysis JSON including all ingredients and totals
4. [PERSIST] Call save_recipe_analysis with operation=create to save to local file
5. [CULINARY] Self-check substitutions make sense for the dish before finalizing
6. Give final answer only after all tools are called

CONVERSATION LOOP — use previous results:
- Each tool result feeds into the next step
- fetch_nutrition results → build totals → pass to suggest_substitutions
- Never repeat a tool call already completed

SELF-CHECKS before final answer:
- Are total calories plausible for this dish type?
- Does each substitution maintain the dish character?
- Did health score improve after substitutions?
- Are all ingredients accounted for?

ERROR HANDLING:
- Ingredient not found in USDA → use fallback estimate, note the warning, continue
- Tool returns error → log it, try next step anyway
- Health score did not improve → explain why and suggest manual alternatives
- Missing quantity → assume 100g and note assumption

OUTPUT FORMAT — final answer must include:
Macros per serving: calories, protein, carbs, fat
Health score: [original]/100 → [optimized]/100
Top substitutions: ingredient → replacement (reason)
Verdict: one sentence on overall healthiness"""


async def run_agent_stream(
    recipe:   str,
    servings: int,
    provider: str | None,
) -> AsyncGenerator[str, None]:

    def event(type_: str, **data) -> str:
        return f"data: {json.dumps({'type': type_, **data})}\n\n"

    user_task = (
        f"Analyze this recipe nutritionally and suggest healthier substitutions:\n\n"
        f"Recipe: {recipe}\n"
        f"Servings: {servings}\n\n"
        f"You MUST follow these steps in order:\n"
        f"Step 1: Call fetch_nutrition for EACH ingredient separately\n"
        f"Step 2: You MUST call suggest_substitutions with all nutrition results as JSON\n"
        f"Step 3: Call save_recipe_analysis with operation=create\n"
        f"Step 4: Give final answer\n\n"
        f"Do NOT skip suggest_substitutions — it is required."
    )

    llm           = LLM()
    messages      = [{"role": "user", "content": user_task}]
    answer        = ""
    display_data  = {}
    # Collect nutrition data from fetch_nutrition calls
    all_nutrition = []
    sub_result    = {}

    try:
        for turn in range(1, 12):
            yield event("thinking", turn=turn, provider=provider or "auto")
            print(f"[turn {turn}] calling LLM...")

            try:
                reply = llm.chat(
                    messages     = messages,
                    system       = SYSTEM_PROMPT,
                    tools        = TOOLS,
                    tool_choice  = "auto",
                    provider     = provider,
                    temperature  = 0,
                    max_tokens   = 2048,
                    reasoning    = "low",    # ✅ Gemini supports this
                    cache_system = True,     # ✅ Caches system prompt across turns
                )
                print(f"[turn {turn}] ok — provider={reply.get('provider')} stop={reply.get('stop_reason')} reasoning={reply.get('reasoning_applied')} cache_read={reply.get('cache_read_input_tokens',0)}")
            except Exception as e:
                print(f"[turn {turn}] LLM ERROR: {e}")
                yield event("error", message=f"LLM error: {str(e)}")
                return

            # Update thinking step
            yield event("thinking",
                        turn     = turn,
                        provider = reply.get("provider", ""),
                        model    = reply.get("model", ""),
                        tokens   = reply.get("output_tokens", 0))

            tool_calls = reply.get("tool_calls") or []

            if not tool_calls:
                answer = reply.get("text", "").strip()

                # Compute per_serving from fetched ingredients
                macros = ["calories","protein_g","carbs_g","fat_g","fiber_g","saturated_fat_g","sodium_mg","sugar_g"]
                totals = {m: sum(n.get(m, 0) for n in all_nutrition) for m in macros}
                per_serving = {m: round(v / max(servings, 1), 2) for m, v in totals.items()}

                # Merge with suggest_substitutions result
                display_data = {
                    **sub_result,
                    "per_serving": per_serving if any(v > 0 for v in per_serving.values()) else sub_result.get("per_serving", {}),
                }

                # Don't yield final yet — verifier runs first so verdict
                # arrives before final and showResults() sees it.
                break

            # Echo assistant turn
            messages.append({
                "role":       "assistant",
                "content":    reply.get("text", "") or "",
                "tool_calls": tool_calls,
            })

            # Emit tool calls to UI
            parallel = len(tool_calls) > 1
            for tc in tool_calls:
                yield event("tool_call",
                            tool     = tc["name"],
                            args     = tc.get("arguments", {}),
                            parallel = parallel)

            # Execute tools
            tool_messages = []
            for tc in tool_calls:
                print(f"[turn {turn}] executing tool: {tc['name']}")
                result_text = await execute_tool(tc["name"], tc.get("arguments") or {}, recipe)
                print(f"[turn {turn}] tool result: {result_text[:100]}")
                yield event("tool_result", tool=tc["name"], result=result_text)

                # Collect results for display
                try:
                    parsed = json.loads(result_text)
                    if tc["name"] == "fetch_nutrition" and "calories" in parsed:
                        all_nutrition.append(parsed)
                    elif tc["name"] == "suggest_substitutions":
                        sub_result = parsed
                except Exception:
                    pass

                tool_messages.append({
                    "role":         "tool",
                    "tool_call_id": tc["id"],
                    "tool_name":    tc["name"],
                    "content":      result_text,
                })

            messages.extend(tool_messages)

        # ── Verifier ───────────────────────────────────────────
        if not answer:
            answer = "Recipe analyzed."  # ensure verifier always runs
        try:
            from agent import OptimizationVerdict
            schema  = OptimizationVerdict.model_json_schema()
            v_reply = llm.chat(
                prompt  = f"Verify this recipe nutrition analysis:\n{answer[:400]}\nDid health improve? Are substitutions culinarily valid?",
                system  = "You are a strict nutrition verifier. Be concise.",
                response_format = {
                    "type":   "json_schema",
                    "schema": schema,
                    "name":   "OptimizationVerdict",
                    "strict": True,
                },
                temperature = 0,
                max_tokens  = 512,
            )
            # Gateway returns parsed when structured output validates OK.
            # Fall back to parsing the raw text when parsed is absent
            # (e.g. LLM wrapped JSON in markdown fences and the strict
            # validator raised, or the provider returned plain JSON text).
            v_data = v_reply.get("parsed")
            if not v_data:
                raw = v_reply.get("text", "")
                # Strip markdown code fences if present
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                try:
                    v_data = json.loads(raw.strip())
                except Exception:
                    v_data = None
            if v_data:
                v = OptimizationVerdict.model_validate(v_data)
                yield event("verdict",
                            passed          = v.passed,
                            health_improved = v.health_improved,
                            original_score  = v.original_score,
                            optimized_score = v.optimized_score,
                            culinary_valid  = v.culinary_valid,
                            key_improvement = v.key_improvement,
                            reason          = v.reason)
            else:
                print(f"[verifier] could not parse verdict from: {v_reply.get('text','')[:100]}")
        except Exception as e:
            print(f"[verifier] skipped: {e}")

        # Final event always sent after verifier so the browser has verdict
        # data in resultData before showResults() is called.
        yield event("final", answer=answer, display_data=display_data)

    except Exception as e:
        print(f"[agent] ERROR: {e}")
        yield event("error", message=str(e))


# ── Routes ─────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((HERE / "index.html").read_text(encoding="utf-8"))


@app.post("/analyze")
async def analyze(req: AnalyzeRequest):
    return StreamingResponse(
        run_agent_stream(req.recipe, req.servings, req.provider),
        media_type  = "text/event-stream",
        headers     = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    uvicorn.run("web_server:app", host="0.0.0.0", port=8000, reload=False)
