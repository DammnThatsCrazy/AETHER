# Hybrid Harness — Claude orchestrates, DeepSeek executes

This folder configures a **hybrid Claude Code harness**: **Claude** is the main
orchestrator/driver (git, architecture, review); **DeepSeek** executes
well-scoped, mechanical sub-tasks at lower cost.

> **The one constraint that shapes everything below.**
> `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` are **global** — they apply to
> *every* request Claude Code makes, orchestrator included. And
> `CLAUDE_CODE_SUBAGENT_MODEL` only changes the model **name** in the request,
> not its **destination**. So you **cannot** split providers with env vars
> alone: point the base URL at DeepSeek and your orchestrator goes to DeepSeek
> too. The split is achieved with a **local router** that speaks the Anthropic
> API to Claude Code and fans out to two upstreams by model.

We use [`claude-code-router`](https://github.com/musistudio/claude-code-router)
(CCR). A model-name-based alternative (LiteLLM) is documented at the end.

```
Claude Code ──► http://127.0.0.1:3456 (local router) ──┬─► api.anthropic.com  (orchestrator = Claude)
   base URL = the router                               └─► api.deepseek.com   (sub-agent/background = DeepSeek)
```

## Files here

| File | Purpose |
|---|---|
| `README.md` | This guide. |
| `claude-code-router.config.example.json` | Example router config. Copy to `~/.claude-code-router/config.json`, fill in keys. |
| `settings.local.example.json` | Optional: copy to `../settings.local.json` (repo-local, gitignored) to auto-point this repo at the router. |
| `../agents/deepseek-executor.md` | The sub-agent Claude delegates mechanical work to. `model: haiku` → routed to DeepSeek. |

---

## Prerequisites

- Node.js 18+ (`node -v`)
- Your **Anthropic API key** and your **DeepSeek API key**
- Claude Code installed

> 🔑 **About the DeepSeek key:** it goes **only** into your local
> `~/.claude-code-router/config.json` (below). Do **not** paste it into a chat,
> a commit, or any file in this repo. Nothing that gets committed ever needs it.

## Step 1 — Install the router

```bash
npm install -g @musistudio/claude-code-router
ccr version
```

## Step 2 — Configure the router (this file holds your keys)

```bash
mkdir -p ~/.claude-code-router
cp .claude/hybrid-harness/claude-code-router.config.example.json ~/.claude-code-router/config.json
# edit the file: replace every REPLACE_* value with a real key/secret
chmod 600 ~/.claude-code-router/config.json
```

What the `Router` block does — CCR routes by **request type**, not by the raw
model name Claude Code sends:

- `default` / `think` / `longContext` / `webSearch` → **Claude** (orchestration,
  reasoning, big context, and web search all stay on the main model)
- `background` → **DeepSeek** (`deepseek-v4-flash`)

`deepseek-v4-flash` / `deepseek-v4-pro` are DeepSeek's current V4 model ids
(they replaced `deepseek-chat` / `deepseek-reasoner`).

## Step 3 — Point Claude Code at the router and route sub-agents to DeepSeek

Start the router, then launch Claude Code so its traffic flows through it:

```bash
ccr start            # or: ccr restart after editing config
ccr status           # confirm it's up; note the log path
ccr code             # launches Claude Code pre-wired to the router
```

`ccr code` sets `ANTHROPIC_BASE_URL` and the router token for you. The last
piece is making **sub-agents** land on the DeepSeek route. Two modes:

**A. Selective (default, recommended).** Only tasks you hand to the
`deepseek-executor` sub-agent go to DeepSeek; everything else stays Claude. This
is already wired: `../agents/deepseek-executor.md` has `model: haiku`, and CCR
sends haiku-tier requests down the `background` route → DeepSeek. **Leave
`CLAUDE_CODE_SUBAGENT_MODEL` unset** for this mode (it would override the
agent's frontmatter).

**B. Blanket.** Send *every* sub-agent to DeepSeek:

```bash
export CLAUDE_CODE_SUBAGENT_MODEL=haiku   # NOT "deepseek-v4-flash" — see note
```

> ⚠️ With CCR, do **not** set `CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash`.
> CCR routes on request *type*; a literal `deepseek-v4-flash` name isn't
> recognized as `background`, so it falls through to `default` and your
> sub-agents would silently run on **Claude**. Use the `haiku` alias, which CCR
> maps to the DeepSeek `background` route. (If you want the literal DeepSeek id
> to work, use LiteLLM — see the end.)

Optional convenience: `cp .claude/hybrid-harness/settings.local.example.json
.claude/settings.local.json` to auto-point *this repo* at the router without
`ccr code`. Only do this while the router is running, or Claude Code in this repo
will fail to reach `127.0.0.1:3456`. `.claude/settings.local.json` is gitignored.

## Step 4 — Authentication, safely

- **Keys live in exactly one place:** `~/.claude-code-router/config.json`,
  `chmod 600`. Claude Code never sees your real Anthropic/DeepSeek keys — only
  the router's local `APIKEY`.
- **Never commit secrets.** Filled-in configs stay out of the repo; the
  `.example` files here carry placeholders only. `.claude/settings.local.json`
  is already gitignored.
- **Loopback only.** Keep `HOST: "127.0.0.1"` (never `0.0.0.0`) so no other
  machine can reach your keyed proxy; the `APIKEY` stops other local processes
  from using it.
- If a key ever lands in shell history, clear it (`history -d <n>`) and **rotate
  it** in the provider console.

## Step 5 — Verify the split is real

Prove it from **both** sides:

1. **Orchestrator is still Claude** — in Claude Code run `/status`; the main
   model should read as your Claude model and the base URL as
   `http://127.0.0.1:3456`.
2. **Watch where requests actually go** — tail the router log (path from
   `ccr status`, or open `ccr ui`):
   ```bash
   tail -f ~/.claude-code-router/*.log
   ```
   Main turns resolve to `anthropic,claude-...`; delegated turns to
   `deepseek,deepseek-v4-flash`.
3. **Trigger a delegation** — ask Claude: *"Use the deepseek-executor sub-agent
   to list every TODO comment in this repo and summarize them."* The log line
   for that turn should show the `deepseek` upstream.
4. **Ground truth** — after a mixed session, the Anthropic Console shows
   main-model tokens and the DeepSeek dashboard shows sub-agent tokens. DeepSeek
   usage staying at zero means sub-agents aren't routing — recheck Step 3.

---

## How this maps to the repo

- **`CLAUDE.md` → "Hybrid Harness Rules"** tells the orchestrator *when* to
  delegate (mechanical, well-scoped work) and *when not to* (architecture,
  generated docs, contracts, versioning stay on Claude). CLAUDE.md shapes
  delegation behavior; it does **not** route traffic — the router does.
- **`.claude/agents/deepseek-executor.md`** is the delegation target. Its
  `model: haiku` is what lands it on DeepSeek via the router. With no router
  running it falls back to a Claude haiku-class model, so this repo's shared CI
  behavior is unchanged for anyone who hasn't set up the harness.

## Caveats worth knowing

- **Billing / subscription:** routing through a custom base URL means the main
  Claude model bills to your Anthropic **API key**, not a Claude Pro/Max
  subscription — you can't mix subscription-auth main + gateway sub-agents in
  one process. Claude turns bill to Anthropic; DeepSeek turns to DeepSeek.
- **Data handling:** delegated prompts include repo code/context and are sent to
  **DeepSeek (a third party)**. Confirm that's acceptable for this codebase, and
  keep sensitive/architectural work on Claude.
- **Tool-call fidelity:** DeepSeek speaks OpenAI-style function calling (the
  router translates); complex tool-use turns can be less reliable than on
  Claude. `deepseek-v4-flash` is the right cheap default; note DeepSeek "thinking"
  is now a request parameter, not a separate model, and can quietly raise cost.
- **Repo CI scope:** a weaker executor editing generated docs, validators,
  contracts, or `pyproject.toml` is a fast way to fail `make ci-check`. The
  `deepseek-executor` agent and CLAUDE.md both fence those off — keep it that way.

## Alternative: LiteLLM (route by exact model name)

If you'd rather have `CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash` work
literally (name-based routing instead of CCR's type-based routing):

```bash
pip install 'litellm[proxy]'
# litellm.yaml maps model_name: claude-sonnet-5 -> anthropic,
#                                deepseek-v4-flash -> deepseek
litellm --config litellm.yaml                 # Anthropic-compatible endpoint
export ANTHROPIC_BASE_URL="http://127.0.0.1:4000"
export CLAUDE_CODE_SUBAGENT_MODEL="deepseek-v4-flash"   # works literally here
```

Same global-base-URL principle; just a router that keys on the model name your
env var sets. If you switch to LiteLLM, set `../agents/deepseek-executor.md`'s
`model:` to `deepseek-v4-flash` to match.
