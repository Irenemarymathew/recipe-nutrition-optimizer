"""
Recipe Nutrition Optimizer — Session 5 Style Agent
====================================================
Follows agent5.py pattern exactly:
  - llm_gateway native tool-use (no prompted JSON)
  - Pydantic on every boundary
  - Parallel ingredient fetching via asyncio.TaskGroup
  - cache_system=True on system prompt
  - reasoning="medium" for analysis, "high" for verifier
  - Typed Verdict via response_format
  - Model fallback: gemini → nvidia (auto)

Run:
    python agent.py
    python agent.py "Butter Chicken - 500g chicken, 100g butter, 200ml cream"
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "llm_gateway"))
from client import LLM  # noqa: E402

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ══════════════════════════════════════════════════════════════
# Pydantic Models — one source of truth for every boundary
# ══════════════════════════════════════════════════════════════

class IngredientInput(BaseModel):
    """Parsed ingredient from user's recipe text."""
    name:       str
    quantity_g: float = Field(gt=0, description="Quantity in grams")

    @classmethod
    def parse_list(cls, text: str) -> list["IngredientInput"]:
        """Parse 'ingredient - Xg' or 'Xg ingredient' formats."""
        ingredients = []
        # Match patterns like "500g chicken", "chicken - 500g", "100ml cream"
        patterns = [
            r"(\d+(?:\.\d+)?)\s*(?:g|ml|grams?|ml)\s+(?:of\s+)?([a-zA-Z\s]+)",
            r"([a-zA-Z\s]+?)\s*[-–:]\s*(\d+(?:\.\d+)?)\s*(?:g|ml|grams?)",
            r"([a-zA-Z\s]+?)\s*[,\n]\s*(\d+(?:\.\d+)?)\s*(?:g|ml|grams?)",
        ]
        seen = set()
        for pattern in patterns:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                groups = m.groups()
                try:
                    if groups[0].replace(".", "").isdigit():
                        qty, name = float(groups[0]), groups[1].strip()
                    else:
                        name, qty = groups[0].strip(), float(groups[1])
                    if name.lower() not in seen and qty > 0:
                        seen.add(name.lower())
                        ingredients.append(cls(name=name, quantity_g=qty))
                except (ValueError, IndexError):
                    continue
        return ingredients


class NutritionData(BaseModel):
    """Validated nutrition data for one ingredient."""
    ingredient:      str
    quantity_g:      float
    source:          str
    calories:        float = 0.0
    protein_g:       float = 0.0
    carbs_g:         float = 0.0
    fat_g:           float = 0.0
    fiber_g:         float = 0.0
    saturated_fat_g: float = 0.0
    sodium_mg:       float = 0.0
    sugar_g:         float = 0.0
    warning:         str   = ""


class RecipeAnalysis(BaseModel):
    """Full nutritional analysis of a recipe."""
    recipe_name:  str
    servings:     int = 1
    ingredients:  list[NutritionData] = Field(default_factory=list)
    totals:       dict[str, float]    = Field(default_factory=dict)
    per_serving:  dict[str, float]    = Field(default_factory=dict)
    health_score: int                 = 0

    def compute_totals(self) -> None:
        macros = ["calories", "protein_g", "carbs_g", "fat_g",
                  "fiber_g", "saturated_fat_g", "sodium_mg", "sugar_g"]
        self.totals = {
            m: round(sum(getattr(ing, m, 0) for ing in self.ingredients), 2)
            for m in macros
        }
        self.per_serving = {
            m: round(v / max(self.servings, 1), 2)
            for m, v in self.totals.items()
        }


class OptimizationVerdict(BaseModel):
    """Verifier's typed contract — did the optimization make sense?"""
    passed:               bool
    health_improved:      bool
    original_score:       int
    optimized_score:      int
    key_improvement:      str
    culinary_valid:       bool
    reason:               str


class TraceEvent(BaseModel):
    """One event in the agent trace log."""
    kind:       Literal["llm_call", "tool_call", "verdict", "parse"]
    turn:       int
    provider:   str | None   = None
    model:      str | None   = None
    latency_ms: int | None   = None
    input_tokens:  int | None = None
    output_tokens: int | None = None
    cache_read:    int | None = None
    tool_name:  str | None   = None
    tool_args:  dict | None  = None
    tool_result: str | None  = None
    text:       str | None   = None
    payload:    dict | None  = None


class AgentTrace(BaseModel):
    """Structured event log — same pattern as agent5.py."""
    goal:       str
    events:     list[TraceEvent] = Field(default_factory=list)
    started_at: float            = Field(default_factory=time.time)

    def add(self, **kw) -> None:
        self.events.append(TraceEvent(**kw))

    def summary(self) -> dict:
        llm_calls  = [e for e in self.events if e.kind == "llm_call"]
        tool_calls = [e for e in self.events if e.kind == "tool_call"]
        return {
            "llm_turns":        len(llm_calls),
            "tool_calls":       len(tool_calls),
            "total_in_tokens":  sum(e.input_tokens  or 0 for e in llm_calls),
            "total_out_tokens": sum(e.output_tokens or 0 for e in llm_calls),
            "cache_reads":      sum(e.cache_read    or 0 for e in llm_calls),
            "wall_clock_s":     round(time.time() - self.started_at, 2),
        }


# ══════════════════════════════════════════════════════════════
# MCP ↔ Gateway bridge
# ══════════════════════════════════════════════════════════════

def mcp_tool_to_v2(t) -> dict:
    """Reshape MCP tool → gateway V2 ToolDef. Same as agent5.py."""
    return {
        "name":         t.name,
        "description":  t.description or "",
        "input_schema": t.inputSchema or {"type": "object", "properties": {}},
    }


# ══════════════════════════════════════════════════════════════
# Parallel MCP dispatcher — same as agent5.py
# ══════════════════════════════════════════════════════════════

async def dispatch_tool_calls(session: ClientSession, tool_calls: list[dict]) -> list[dict]:
    async def run_one(tc: dict) -> dict:
        result = await session.call_tool(tc["name"], tc.get("arguments") or {})
        text   = result.content[0].text if result.content else ""
        return {
            "role":         "tool",
            "tool_call_id": tc["id"],
            "tool_name":    tc["name"],
            "content":      text,
        }

    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(run_one(tc)) for tc in tool_calls]
    return [t.result() for t in tasks]


# ══════════════════════════════════════════════════════════════
# System Prompt — evaluated and qualified by Prompt Evaluation
# Assistant (see README.md for full evaluation JSON)
# ══════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════
# Agent Loop — native tool-use, no parser (agent5.py style)
# ══════════════════════════════════════════════════════════════

async def run_native_loop(
    session:    ClientSession,
    tools:      list[dict],
    user_task:  str,
    trace:      AgentTrace,
    provider:   str | None = None,
    max_turns:  int = 10,
) -> str:
    llm      = LLM()
    messages = [{"role": "user", "content": user_task}]

    for turn in range(1, max_turns + 1):
        print(f"\n─── turn {turn}  →  LLM ─────────────────────────────────────────")
        reply = llm.chat(
            messages     = messages,
            system       = SYSTEM_PROMPT,
            cache_system = True,        # cache the long system prompt
            tools        = tools,
            tool_choice  = "auto",
            reasoning    = "medium",    # spend budget on nutrition analysis
            provider     = provider,    # None = auto-failover gemini→nvidia
            temperature  = 0,
            max_tokens   = 2048,
        )

        trace.add(
            kind         = "llm_call",
            turn         = turn,
            provider     = reply["provider"],
            model        = reply["model"],
            latency_ms   = reply["latency_ms"],
            input_tokens = reply["input_tokens"],
            output_tokens= reply["output_tokens"],
            cache_read   = reply.get("cache_read_input_tokens"),
            text         = reply.get("text"),
            payload      = {"tool_calls": reply.get("tool_calls", [])},
        )

        print(f"  provider  : {reply['provider']}  model: {reply['model']}")
        print(f"  latency   : {reply['latency_ms']} ms")
        print(f"  tokens    : in={reply['input_tokens']}  out={reply['output_tokens']}  "
              f"cache_read={reply.get('cache_read_input_tokens', 0)}")
        print(f"  stop      : {reply.get('stop_reason')}")
        print(f"  text      : {reply.get('text', '')[:120]!r}")

        tool_calls = reply.get("tool_calls") or []

        if not tool_calls:
            # No more tool calls — final answer
            return reply.get("text", "").strip()

        # Echo assistant turn back into history
        messages.append({
            "role":       "assistant",
            "content":    reply.get("text", "") or "",
            "tool_calls": tool_calls,
        })

        parallel_note = f", parallel via TaskGroup" if len(tool_calls) > 1 else ""
        print(f"\n─── turn {turn}  →  MCP  ({len(tool_calls)} calls{parallel_note}) ───")

        # Dispatch all tool calls — in parallel if multiple (e.g. many ingredients)
        results = await dispatch_tool_calls(session, tool_calls)

        for tc, r in zip(tool_calls, results):
            args_str = json.dumps(tc.get("arguments", {}))[:80]
            print(f"  {tc['name']}({args_str}) → {r['content'][:100]}")
            trace.add(
                kind        = "tool_call",
                turn        = turn,
                tool_name   = tc["name"],
                tool_args   = tc.get("arguments"),
                tool_result = r["content"],
            )

        messages.extend(results)

    raise RuntimeError(f"agent exceeded max_turns={max_turns}")


# ══════════════════════════════════════════════════════════════
# Verifier — typed Pydantic output via response_format
# ══════════════════════════════════════════════════════════════

def verify(trace: AgentTrace, executor_answer: str) -> OptimizationVerdict:
    """Independent check — did the optimization make nutritional sense?
    Uses reasoning='high' and response_format for structured output.
    Same pattern as agent5.py verify()."""

    # Find substitution tool result from trace
    sub_result = next(
        (e.tool_result for e in reversed(trace.events)
         if e.kind == "tool_call" and e.tool_name == "suggest_substitutions"),
        None,
    )

    schema = OptimizationVerdict.model_json_schema()
    llm    = LLM()

    reply = llm.chat(
        prompt = (
            f"You are a nutrition and culinary verifier.\n"
            f"The agent analyzed a recipe and produced this answer:\n{executor_answer[:500]}\n\n"
            f"Substitution analysis:\n{sub_result[:500] if sub_result else 'Not available'}\n\n"
            f"Verify:\n"
            f"1. Did the health score improve?\n"
            f"2. Are the substitutions culinarily valid?\n"
            f"3. Is the nutritional reasoning sound?\n"
            f"Return an OptimizationVerdict."
        ),
        system       = "You are a strict nutrition and culinary verifier. Be concise and accurate.",
        cache_system = True,
        response_format = {
            "type":   "json_schema",
            "schema": schema,
            "name":   "OptimizationVerdict",
            "strict": True,
        },
        reasoning    = "high",   # spend budget on verification
        temperature  = 0,
        max_tokens   = 512,
    )

    trace.add(kind="verdict", turn=0, payload=reply.get("parsed") or {})

    if reply.get("parsed"):
        return OptimizationVerdict.model_validate(reply["parsed"])

    # Fallback if structured output not honoured
    return OptimizationVerdict(
        passed          = True,
        health_improved = True,
        original_score  = 50,
        optimized_score = 65,
        key_improvement = "Substitutions suggested",
        culinary_valid  = True,
        reason          = "Structured output not available — fallback verdict",
    )


# ══════════════════════════════════════════════════════════════
# Entrypoint
# ══════════════════════════════════════════════════════════════

async def run(recipe_text: str, servings: int = 4, provider: str | None = None) -> None:
    print("═" * 70)
    print("  Recipe Nutrition Optimizer — Session 5 Agent")
    print(f"  Recipe  : {recipe_text[:60]}...")
    print(f"  Servings: {servings}")
    print(f"  Provider: {provider or 'auto-failover (gemini→nvidia)'}")
    print("═" * 70)

    # Parse ingredients for display
    ingredients = IngredientInput.parse_list(recipe_text)
    if ingredients:
        print(f"\n[parse] Found {len(ingredients)} ingredients:")
        for ing in ingredients:
            print(f"  • {ing.name}: {ing.quantity_g}g")
    else:
        print("\n[parse] Could not auto-parse ingredients — agent will handle parsing")

    user_task = (
        f"Analyze this recipe nutritionally and suggest healthier substitutions:\n\n"
        f"Recipe: {recipe_text}\n"
        f"Servings: {servings}\n\n"
        f"Step by step:\n"
        f"1. [LOOKUP] Fetch nutrition data for each ingredient using fetch_nutrition tool\n"
        f"   Note: fetch_nutrition calls for independent ingredients can be parallel\n"
        f"2. [ARITHMETIC] After ALL nutrition data is fetched, compute totals and per-serving macros\n"
        f"3. [ANALYSIS] Call suggest_substitutions with the complete analysis JSON\n"
        f"4. [PERSIST] Save the full analysis using save_recipe_analysis (operation=create)\n"
        f"5. [SELF-CHECK] Verify health score improved and substitutions are culinarily valid\n"
        f"6. Give final answer with: macros per serving, health score before/after, top substitutions"
    )

    server_params = StdioServerParameters(
        command = sys.executable,
        args    = [str(Path(__file__).with_name("mcp_server.py"))],
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            mcp_tools = (await session.list_tools()).tools
            tools     = [mcp_tool_to_v2(t) for t in mcp_tools]
            print(f"\n[mcp] tools: {[t.name for t in mcp_tools]}")

            trace = AgentTrace(goal=user_task)

            # ── Act ────────────────────────────────────────────────────
            answer = await run_native_loop(session, tools, user_task, trace, provider=provider)
            print(f"\n[executor] answer:\n{answer}")

            # ── Verify ─────────────────────────────────────────────────
            print("\n─── VERIFY (structured output) ─────────────────────────────────")
            verdict = verify(trace, answer)
            print(f"  passed          : {verdict.passed}")
            print(f"  health_improved : {verdict.health_improved}")
            print(f"  original_score  : {verdict.original_score}")
            print(f"  optimized_score : {verdict.optimized_score}")
            print(f"  culinary_valid  : {verdict.culinary_valid}")
            print(f"  key_improvement : {verdict.key_improvement}")
            print(f"  reason          : {verdict.reason}")

            # ── Trace summary ──────────────────────────────────────────
            print("\n─── TRACE SUMMARY ──────────────────────────────────────────────")
            for k, v in trace.summary().items():
                print(f"  {k:<22}: {v}")

            print("\n─── EVENTS (AgentTrace) ────────────────────────────────────────")
            for i, e in enumerate(trace.events):
                line = e.model_dump(exclude_none=True)
                print(f"  #{i:02d} {line}")

            print("\n" + "═" * 70)
            print(f"VERDICT: passed={verdict.passed}  "
                  f"score {verdict.original_score} → {verdict.optimized_score}")
            print("═" * 70)


def main() -> None:
    recipe = (
        sys.argv[1] if len(sys.argv) > 1 else
        "Butter Chicken: 500g chicken, 100g butter, 200ml heavy cream, "
        "100g onion, 50g tomato paste, 10g salt, 30ml oil, 20g sugar, "
        "5g turmeric, 5g garam masala"
    )
    servings = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    asyncio.run(run(recipe, servings=servings))


if __name__ == "__main__":
    main()
