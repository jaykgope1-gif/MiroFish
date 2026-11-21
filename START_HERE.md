# Start here: run MiroFish live on your computer

About 30 minutes the first time. After that, two commands.

## 1. Install the tools (once)

| Tool | Get it | Check it works |
|---|---|---|
| Node.js 18 or newer | nodejs.org (LTS version) | `node -v` |
| Python 3.11 or 3.12 (not 3.13) | python.org | `python --version` |
| uv | docs.astral.sh/uv (one-line installer) | `uv --version` |
| Git | git-scm.com | `git --version` |

On Windows, use PowerShell for the commands below.

## 2. Get the code (once)

```bash
git clone https://github.com/jaykgope1-gif/MiroFish.git
```

```bash
cd MiroFish
```

```bash
npm run setup:all
```

The last one installs everything and takes a few minutes.

## 3. Get your keys (once)

Pick **one** AI provider:

**A. Free, to start (Groq).** No card needed. Good for your own tests and demos; never put client documents through it.

1. Go to console.groq.com and sign in (Google sign-in works).
2. Click **API Keys**, then **Create API Key**, and copy it. It starts with `gsk_`.

**B. Paid, for client work (Claude).** About $10 (R185) of credit lasts for many runs.

1. Go to platform.claude.com, sign in, and add a card under Billing.
2. Go to **Settings > API keys > Create key**, and copy it. It starts with `sk-ant-`.

**Zep** (free; needed to build worlds from documents and to write reports):

1. Go to app.getzep.com and sign up.
2. Open **Project Settings**, then **Project Keys**, then **Add Key**. Give it a name and create it. It usually starts with `zpk_`.

Copy `.env.example` to a new file called `.env` in the `MiroFish` folder and fill in **one** of these.

For Groq (free):

```
LLM_PROVIDER=openai
LLM_API_KEY=gsk_your-key
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL_NAME=openai/gpt-oss-20b
SIMULATION_LLM_CONCURRENCY=2
ZEP_API_KEY=zpk_your-key
```

For Claude:

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-key
ZEP_API_KEY=zpk_your-key
USD_ZAR_RATE=18.5
```

Set `USD_ZAR_RATE` to today's rand-dollar rate. Never share the `.env` file or put it on GitHub; it is already excluded from git.

Groq's free tier allows roughly one full simulation a day. When a run stops with "rate limit", wait until the next day or switch to Claude.

## 4. Check, then run

```bash
npm run check
```

It tests your keys with one tiny request and tells you in plain words what to fix. When it says **Ready**:

```bash
npm run dev
```

Your browser opens MiroFish at http://localhost:3000.

**Try the ready-made TenderFind world** (no document or Zep needed). With `npm run dev` still running, open a second terminal in the `MiroFish` folder and run:

```bash
cd backend && uv run python scripts/god_demo/make_tenderfind.py --start
```

Then watch it at http://localhost:3000/god/sim_tenderfind_live.

**Or build a world from a document** (needs Zep): create a project on the home page, prepare and start a simulation, then watch and steer it in the God View at http://localhost:3000/god. On Claude, the status line shows what the run has cost so far, and a run stops itself at R50.

## 5. Run a stress-test for a client

```bash
cd backend
```

```bash
uv run python ../sales_engine/stress_test.py tender bid.pdf --client "ABC Civils" --dry-run
```

The dry run shows the cost without sending anything. Then run it for real with the client's written consent:

```bash
uv run python ../sales_engine/stress_test.py tender bid.pdf --client "ABC Civils" --consent "WhatsApp consent, A. Nkosi, 12 Nov 2026"
```

The report lands in `sales_engine/reports/`. Read `sales_engine/README.md` for the rest.

## If something goes wrong

- Run `npm run check` first; it names most problems.
- "Port already in use": another MiroFish is running. Close it, or restart your computer.
- To try the God View without any keys: `npm run demo` (canned text, not a real run).
