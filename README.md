# Recipe Nutrition Optimizer
### EAG v3 — Session 5 Assignment

An AI agent that analyzes any recipe nutritionally, fetches real macro data from the USDA FoodData Central API, suggests healthier ingredient substitutions, and displays a before/after health score — all powered by a multi-model LLM gateway with automatic fallback.

---

## Demo

> Paste any recipe → Agent fetches real nutrition data → Suggests healthier substitutions → Shows health score improvement

---

## Features

- **Real nutrition data** — fetches from USDA FoodData Central API (free, no key needed)
- **Multi-model fallback** — Gemini → NVIDIA auto-routing via llm_gateway
- **Parallel tool dispatch** — all ingredients fetched simultaneously
- **Pydantic on every boundary** — typed models for input, output, trace, and verdict
- **Structured verifier** — independent LLM call validates the optimization
- **Live reasoning chain** — watch the agent think step by step in the browser
- **9/9 prompt evaluation** — system prompt evaluated against instructor's criteria

---

## Architecture

```
Browser (index.html)
      ↓
FastAPI Web Server (web_server.py)
      ↓
LLM Agent Loop
      ↓
llm_gateway (port 8100)
  → Gemini 3.1 Flash Lite(primary)
  → NVIDIA DeepSeek (fallback)
      ↓
3 MCP Tools:
  fetch_nutrition()        ← USDA FoodData Central API
  suggest_substitutions()  ← Rule-based + gap analysis
  save_recipe_analysis()   ← CRUD on local analyses.json
```

---

## Session 5 Features Used

| Feature | Implementation |
|---|---|
| **Pydantic models** | `IngredientInput`, `NutritionData`, `RecipeAnalysis`, `OptimizationVerdict`, `AgentTrace`, `TraceEvent` |
| **llm_gateway** | `LLM().chat()` → port 8100, native tool-use |
| **Multi-model fallback** | gemini → nvidia, capability-aware auto-routing |
| **Native tool-use** | `tools=[...]`, reads `tool_calls[]` — no JSON parser |
| **Structured output** | `response_format=OptimizationVerdict.model_json_schema()` |
| **Typed Verdict** | `OptimizationVerdict.model_validate(reply["parsed"])` |
| **Parallel tool dispatch** | All ingredients fetched in parallel |
| **reasoning="low"** | Reasoning budget passed to gateway |
| **cache_system=True** | System prompt cached across turns |

---

## 3 MCP Tools

| Tool | Type | Description |
|---|---|---|
| `fetch_nutrition(ingredient, quantity_g)` | 🌐 Internet | USDA FoodData Central API — real macro data per ingredient |
| `suggest_substitutions(analysis_json)` | 🧠 Reasoning | Identifies nutritional gaps, suggests specific substitutions |
| `save_recipe_analysis(operation, ...)` | 💾 CRUD | Create / Read / List / Delete on local `analyses.json` |

---

## Prompt Evaluation — 9/9 ✅

The system prompt was evaluated against the instructor's Prompt Evaluation Assistant criteria before building.

```json
{
  "explicit_reasoning": true,
  "structured_output": true,
  "tool_separation": true,
  "conversation_loop": true,
  "instructional_framing": true,
  "internal_self_checks": true,
  "reasoning_type_awareness": true,
  "fallbacks": true,
  "overall_clarity": "All 9 criteria fully satisfied. Numbered reasoning steps with type tags ([LOOKUP], [ARITHMETIC], [ANALYSIS], [PERSIST], [CULINARY]), conversation loop section, 4 self-checks, 4 error handling cases, and strict output format."
}
```

See [prompt_evaluation.md](prompt_evaluation.md) for the full detailed evaluation.

---

## Multi-Step Reasoning Chain

```
Turn 1: [LOOKUP] fetch_nutrition × N ingredients (parallel)
         ↓ real USDA macro data for each
Turn 2: [ANALYSIS] suggest_substitutions(full analysis JSON)
         ↓ gaps identified, substitutions suggested
Turn 3: [PERSIST] save_recipe_analysis(operation=create)
         ↓ saved to analyses.json
Turn 4: [SELF-CHECK] verify calories plausible, substitutions valid
         ↓ final answer with macros + scores
Verifier: OptimizationVerdict — independent structured output check
```

---

## Folder Structure

```
nutrition_optimizer/
├── .env                          ← API keys (not committed)
├── README.md                     ← this file
├── llm_gateway/                ← instructor's gateway
│   ├── main.py
│   ├── providers.py
│   ├── client.py
│   ├── router.py
│   └── ...
└── recipe_nutrition_optimizer/   ← this project
    ├── mcp_server.py             ← 3 MCP tools
    ├── agent.py                  ← terminal agent (Session 5 style)
    ├── web_server.py             ← FastAPI + SSE streaming
    ├── index.html                ← webpage UI
    ├── requirements.txt
    ├── PROMPT_EVALUATION.md      ← full prompt evaluation
    └── analyses.json             ← saved recipe analyses (auto-created)
```

---

## Setup & Run

### 1. Clone and install

```bash
git clone <your-repo-url>
cd nutrition_optimizer

# Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

# Install dependencies
pip install -r llm_gateway/requirements.txt
pip install -r recipe_nutrition_optimizer/requirements.txt
```

### 2. Add API keys

Create `.env` in the `nutrition_optimizer/` folder:

```
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-model
NVIDIA_API_KEY=nvapi-your_nvidia_key
USDA_API_KEY=your_usda_key
```

### 3. Start the gateway (Terminal 1)

```bash
cd llm_gateway
uvicorn main:app --host 0.0.0.0 --port 8100
```

### 4. Start the web server (Terminal 2)

```bash
cd recipe_nutrition_optimizer
python web_server.py
```

### 5. Open browser

```
http://localhost:8000
```

---

## Example Recipes

```
Butter Chicken: 500g chicken, 100g butter, 200ml heavy cream,
100g onion, 50g tomato paste, 10g salt, 30ml oil, 20g sugar,
5g turmeric, 5g garam masala

Creamy Pasta: 300g pasta, 150ml heavy cream, 80g parmesan cheese,
50g butter, 5g salt, 10g black pepper, 100g bacon

Dal Tadka: 200g lentils, 30ml oil, 50g onion, 30g tomato,
5g salt, 5g turmeric, 5g cumin, 10g ghee
```

---

## API Keys

| Service | Where to get | Free tier |
|---|---|---|
| Gemini | [aistudio.google.com](https://aistudio.google.com/apikey) | 1M tokens/day |
| NVIDIA | [build.nvidia.com](https://build.nvidia.com) | 1000 credits |
| USDA FoodData | [fdc.nal.usda.gov](https://fdc.nal.usda.gov/api-guide.html) | Free — add `USDA_API_KEY` to `.env` |

---

## Built With

- [FastAPI](https://fastapi.tiangolo.com/) — web server + SSE streaming
- [Pydantic v2](https://docs.pydantic.dev/) — data validation on every boundary
- [llm_gateway](theschoolofai) — multi-model LLM gateway
- [USDA FoodData Central](https://fdc.nal.usda.gov/) — real nutrition data
- [MCP](https://modelcontextprotocol.io/) — tool protocol

---

*EAG v3 — The School of AI — Session 5 Assignment*
