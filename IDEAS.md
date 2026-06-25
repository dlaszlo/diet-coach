# Development ideas

Future extensions. Not urgent — daily use via the CLI (`./t`) and Claude Code
already works.

---

## 1. Web/mobile AI-coach UI

**Date:** 2026-06-22

**Goal:** an "always at hand" version — a UI that behaves like a personal
trainer: tells me the daily plan, tracks it, adapts. Long-term it supports a
lifestyle change; as I "learn it", I need it less and less.

**Key idea:** the "brain" already exists. The web app would **call the same thing
we use now via Claude Code** — only the surface is different:
- system prompt = the `diet-coach` skill (+ `CLAUDE.md` entry point)
- context bundle = output of `./t plan brief`
- data = the existing plain-text files (`data/`)

So the frontend is an **added layer, not a rewrite**.

**What makes it "AI-compatible" (4 elements, 3 already done):**
1. Context assembly → ✅ `plan brief`
2. Persona + rules (system prompt) → ✅ `diet-coach` skill
3. Structured output (JSON / "ingredients") → ✅ plan format
4. "Tools" / function calls (log, search OFF, fetch history) → partly done in `./t`

**AI flow for a recipe/suggestion:**
app assembles the brief → Claude API: "plan N days with these rules" → structured
plan + ingredients → app renders it, diffs the list, user accepts/swaps.
"What should I eat now?" and barcode scanning (OFF) work the same way.

**Gradual path (less → more work):**
1. stay on CLI + git (current)
2. local web UI (e.g. Streamlit/FastAPI) around `track.py` + a weight-trend chart
3. phone-friendly PWA — logging on the go + camera barcode (OFF)
4. full app with its own backend; switch to SQLite then, but **keep the
   markdown/CSV export** (no hard dependency on an external app)

**Model:** for planning Claude Opus 4.8 (smartest); for routine the cheaper
Sonnet 4.6 / Haiku 4.5. For personal use the token cost is small.

**Limits:** API key + (small) cost; health data goes to the API → send only the
necessary context, the local files stay the user's; the estimate stays rough; a
doctor overrides.

---

## 2. Custom slash commands (`/coach:*`)

Wrap the recurring routines as namespaced Claude Code commands: `/coach:setup`
(onboarding), `/coach:morning`, `/coach:today`, `/coach:eat`, `/coach:close`,
`/coach:plan`, `/coach:replan`, `/coach:week`. Cheap and improves the daily flow.

## 3. Real data via MCP

Connect a smart scale / wearable / Apple Health–Google Fit export over MCP →
automatic weight, steps, sleep (and glucose with a CGM). Removes most manual entry.
