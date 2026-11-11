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

1. **Claude**: go to platform.claude.com, sign in, add a card and buy $10 of credit (about R185), then Settings > API keys > Create key. Copy the key; it starts with `sk-ant-`.
2. **Zep** (for building graphs from documents and for reports): app.getzep.com, free account, create an API key.

Copy `.env.example` to a new file called `.env` in the `MiroFish` folder, and fill in:

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-your-key
ZEP_API_KEY=your-zep-key
USD_ZAR_RATE=18.5
```

Set `USD_ZAR_RATE` to today's rand-dollar rate. Never share the `.env` file or put it on GitHub; it is already excluded from git.

## 4. Check, then run

```bash
npm run check
```

It tests your keys with one tiny request and tells you in plain words what to fix. When it says **Ready**:

```bash
npm run dev
```

Your browser opens MiroFish at http://localhost:3000. Create a project from a document, prepare and start a simulation, then watch and steer it in the God View at http://localhost:3000/god. The status line shows what the run has cost so far; a run stops itself at R50.

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
