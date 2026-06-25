# CLAUDE.md — entry point (auto-loaded)

This project is a personal health / weight-loss diary and meal planner. **All
behavior** — persona, session-start steps, planning process, rules, file schema,
tool usage — lives in the **`diet-coach` skill** (`.claude/skills/diet-coach/`),
which is a self-contained, portable skill: instructions + bundled `scripts/` +
`data.example/` templates. Human-facing setup docs live in the repo-root
`README.md` (kept outside the skill folder, per the skill-authoring guidelines).

At session start, use the **`diet-coach` skill**: it reads `data/profile.md` and
today's diary, then drives logging / planning / coaching. The concrete personal
data lives in the gitignored `data/` folder; communicate in the user's language
(the `language` field in `data/config.json`, otherwise mirror the user).
