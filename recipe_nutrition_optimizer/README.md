# Recipe Nutrition Optimizer
## Session 5 · llm_gateway · Pydantic · MCP · Multi-model Fallback

---

## What It Does

Paste any recipe → Agent:
1. Fetches real nutrition data per ingredient from USDA FoodData API
2. Calculates total macros and per-serving values
3. Identifies nutritional gaps vs daily reference values
4. Suggests specific ingredient substitutions
5. Scores healthiness before and after optimization
6. Verifier checks if optimization made sense

---

## Features Used

| Feature | Implementation |
|---|---|
| Pydantic on every boundary | `IngredientInput`, `NutritionData`, `RecipeAnalysis`, `OptimizationVerdict`, `AgentTrace` |
| llm_gateway native tool-use | `tools=[...]`, reads `tool_calls[]` — no JSON parser |
| Model fallback | gemini → nvidia → groq (capability-aware auto-routing) |
| cache_system=True | System prompt cached on first call |
| reasoning="low" | Analysis loop uses low reasoning budget |
| reasoning="high" | Verifier uses high reasoning budget |
| Parallel tool dispatch | `asyncio.TaskGroup` for independent ingredient fetches |
| Structured output | `response_format=OptimizationVerdict.model_json_schema()` |
| Typed Verdict | `OptimizationVerdict.model_validate(reply["parsed"])` |

---

## 3 MCP Tools

| Tool | Type | Description |
|---|---|---|
| `fetch_nutrition(ingredient, quantity_g)` | Internet | USDA FoodData Central API — real macro data |
| `save_recipe_analysis(operation, ...)` | CRUD | Create/Read/List/Delete on local analyses.json |
| `suggest_substitutions(analysis_json)` | Reasoning | Rule-based + LLM substitution suggestions |

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up .env (one level up from this folder)
```
GEMINI_API_KEY=your_gemini_key
GEMINI_MODEL=gemini-model
NVIDIA_API_KEY=nvapi-your_nvidia_key
USDA_API_KEY=your_usda_key
```

### 3. Start llm_gateway
```bash
cd ../llm_gateway
bash run.sh
# Runs on http://localhost:8100
```

### 4. Run the web server
```bash
python web_server.py
# Open http://localhost:8000
```

### 5. Or run terminal agent directly
```bash
python agent.py "Butter Chicken: 500g chicken, 100g butter, 200ml cream"
python agent.py "Dal Tadka: 200g lentils, 30ml oil, 50g onion" 4
```

---

## Example Recipes to Try

```
Butter Chicken: 500g chicken, 100g butter, 200ml heavy cream, 
100g onion, 50g tomato paste, 10g salt, 30ml oil, 20g sugar

Creamy Pasta: 300g pasta, 150ml heavy cream, 80g parmesan, 
50g butter, 5g salt, 10g black pepper, 100g bacon

Dal Tadka: 200g lentils, 30ml oil, 50g onion, 30g tomato, 
5g salt, 5g turmeric, 5g cumin, 10g ghee
```

---

## File Structure

```
recipe-nutrition-optimizer/
├── mcp_server.py     ← 3 MCP tools
├── agent.py          ← Session 5 terminal agent
├── web_server.py     ← FastAPI + SSE streaming
├── index.html        ← Webpage UI
├── requirements.txt
└── README.md
```
