# System Prompt Evaluation
## Recipe Nutrition Optimizer Agent

---

## The System Prompt

```
You are a Recipe Nutrition Optimizer Agent. Analyze recipes step by step and suggest healthier alternatives.

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
Verdict: one sentence on overall healthiness
```

---

## Evaluation JSON

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
  "overall_clarity": "All 9 criteria fully satisfied. The prompt uses numbered reasoning steps with explicit type tags ([LOOKUP], [ARITHMETIC], [ANALYSIS], [PERSIST], [CULINARY]), a dedicated conversation loop section, 4 self-checks before final answer, 4 specific error handling cases, and a strict parseable output format. Reasoning type tagging directly activates the LLM's meta-reasoning circuits as described in Session 5 curriculum. Ready for production agentic use."
}
```

---

## Evaluation Against Instructor's 9 Criterias

### Criterion 1 — Explicit Reasoning Instructions
**Does the prompt tell the model to reason step-by-step? Does it include instructions like "explain your thinking" or "think before you answer"?**

✅ **PASS**

The prompt opens with `"REASONING — think before each action"` and provides 6 numbered steps the model must follow in order. Each step is tagged with a reasoning type (`[LOOKUP]`, `[ARITHMETIC]`, `[ANALYSIS]`, `[PERSIST]`, `[CULINARY]`) and step 6 explicitly says `"Give final answer only after all tools are called"` — forcing the model to reason through the full pipeline before responding.

---

### Criterion 2 — Structured Output Format
**Does the prompt enforce a predictable output format? Is the output easy to parse or validate?**

✅ **PASS**

The `OUTPUT FORMAT` section explicitly defines the structure of the final answer:
```
Macros per serving: calories, protein, carbs, fat
Health score: [original]/100 → [optimized]/100
Top substitutions: ingredient → replacement (reason)
Verdict: one sentence on overall healthiness
```
This is a rigid, parseable format. The verifier can validate each field independently. The `[original]/100 → [optimized]/100` pattern makes the score comparison machine-readable.

---

### Criterion 3 — Separation of Reasoning and Tools
**Are reasoning steps clearly separated from computation or tool-use steps? Is it clear when to calculate, when to verify, when to reason?**

✅ **PASS**

Each step is explicitly tagged with its type:
- `[LOOKUP]` — tool use (fetch_nutrition)
- `[ARITHMETIC]` — computation (sum macros, divide by servings)
- `[ANALYSIS]` — tool use (suggest_substitutions)
- `[PERSIST]` — tool use (save_recipe_analysis)
- `[CULINARY]` — reasoning (self-check substitutions)

The model is never left to decide what kind of action to take — it is told explicitly at each step.

---

### Criterion 4 — Conversation Loop Support
**Could this prompt work in a multi-turn setting? Is there a way to update the context with results from previous steps?**

✅ **PASS**

The `CONVERSATION LOOP` section explicitly handles this:
```
- Each tool result feeds into the next step
- fetch_nutrition results → build totals → pass to suggest_substitutions
- Never repeat a tool call already completed
```
This tells the model to treat the conversation as a stateful pipeline where each turn's output becomes the next turn's input. The `"Never repeat a tool call"` instruction prevents redundant loops.

---

### Criterion 5 — Instructional Framing
**Are there examples of desired behavior or formats to follow? Does the prompt define exactly how responses should look?**

✅ **PASS**

The prompt uses clear section headers (`REASONING`, `CONVERSATION LOOP`, `SELF-CHECKS`, `ERROR HANDLING`, `OUTPUT FORMAT`) to frame each behavioral expectation. The output format section provides a concrete template with placeholder syntax (`[original]/100 → [optimized]/100`) that shows the model exactly what the response should look like. The reasoning tags (`[LOOKUP]`, `[ARITHMETIC]` etc.) serve as behavioral labels the model is expected to follow.

---

### Criterion 6 — Internal Self-Checks
**Does the prompt instruct the model to self-verify or sanity-check intermediate steps?**

✅ **PASS**

The `SELF-CHECKS` section contains 4 explicit verification questions the model must answer before giving its final response:
```
- Are total calories plausible for this dish type?
- Does each substitution maintain the dish character?
- Did health score improve after substitutions?
- Are all ingredients accounted for?
```
These checks cover numerical plausibility, culinary validity, goal achievement, and completeness — covering all dimensions of the task.

---

### Criterion 7 — Reasoning Type Awareness
**Does the prompt encourage the model to tag or identify the type of reasoning used?**

✅ **PASS**

Every reasoning step is explicitly tagged:
- `[LOOKUP]` — nutritional data retrieval
- `[ARITHMETIC]` — mathematical computation (summing macros, per-serving division)
- `[ANALYSIS]` — gap identification and substitution reasoning
- `[PERSIST]` — data persistence operation
- `[CULINARY]` — domain-specific culinary reasoning

This tagging forces the model to "meta-reason" — identifying what kind of thinking is required at each step, which reduces hallucination and improves accuracy as per the session 5 curriculum.

---

### Criterion 8 — Error Handling or Fallbacks
**Does the prompt specify what to do if an answer is uncertain, a tool fails, or the model is unsure?**

✅ **PASS**

The `ERROR HANDLING` section covers 4 specific failure scenarios:
```
- Ingredient not found in USDA → use fallback estimate, note the warning, continue
- Tool returns error → log it, try next step anyway
- Health score did not improve → explain why and suggest manual alternatives
- Missing quantity → assume 100g and note assumption
```
Each scenario has a specific recovery action, preventing the model from halting or hallucinating when things go wrong.

---

### Criterion 9 — Overall Clarity and Robustness
**Is the prompt easy to follow? Is it likely to reduce hallucination and drift?**

✅ **PASS**

The prompt is organized into 5 clearly labeled sections. Each section has a single responsibility. The numbered steps in the REASONING section create an unambiguous execution order. The combination of:
- Explicit tool call order
- Reasoning type tags
- Self-checks before answering
- Strict output format
- Error recovery instructions

...makes it extremely difficult for the model to hallucinate or drift. The instruction `"Give final answer only after all tools are called"` prevents premature responses.

---

## Score: 9 / 9 ✅

| Criterion | Result |
|---|---|
| 1. Explicit Reasoning Instructions | ✅ PASS |
| 2. Structured Output Format | ✅ PASS |
| 3. Separation of Reasoning and Tools | ✅ PASS |
| 4. Conversation Loop Support | ✅ PASS |
| 5. Instructional Framing | ✅ PASS |
| 6. Internal Self-Checks | ✅ PASS |
| 7. Reasoning Type Awareness | ✅ PASS |
| 8. Error Handling or Fallbacks | ✅ PASS |
| 9. Overall Clarity and Robustness | ✅ PASS |