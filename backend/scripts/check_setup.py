"""
Check that MiroFish is ready to run live, and say what to fix if not.

    npm run check        (from the repository root)

It checks the .env file and the Claude settings, then sends one tiny request
to Claude (costs a fraction of a cent) to prove the key works, and pings
Zep if a Zep key is set. Nothing else is sent anywhere.
"""

import os
import sys

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT_DIR = os.path.dirname(BACKEND_DIR)
ENV_PATH = os.path.join(ROOT_DIR, ".env")
sys.path.insert(0, BACKEND_DIR)

OK, WARN, FAIL = "  OK   ", "  WARN ", "  FAIL "
problems = 0


def report(status, message, fix=None):
    global problems
    print(status + message)
    if fix:
        print("         -> " + fix)
    if status == FAIL:
        problems += 1


def placeholder(value):
    return not value or value.startswith("your_") or value in ("demo-key", "sk-ant-...")


def main():
    print("MiroFish setup check\n")

    if not os.path.exists(ENV_PATH):
        report(FAIL, "No .env file in the repository folder.",
               "Copy .env.example to .env, then fill in ANTHROPIC_API_KEY (and ZEP_API_KEY for graphs and reports).")
        return finish()
    report(OK, f".env found ({ENV_PATH})")

    from app.config import Config  # loads .env

    if Config.LLM_PROVIDER != "anthropic":
        report(FAIL, f"LLM_PROVIDER is '{Config.LLM_PROVIDER}', not 'anthropic'.", "Set LLM_PROVIDER=anthropic in .env.")
        return finish()
    report(OK, "LLM_PROVIDER=anthropic")

    key = Config.ANTHROPIC_API_KEY or ""
    if placeholder(key):
        report(FAIL, "ANTHROPIC_API_KEY is missing or still the example value.",
               "Create a key at platform.claude.com (Settings > API keys; add credit first) and paste it into .env.")
        return finish()
    if not key.startswith("sk-ant-"):
        report(WARN, "ANTHROPIC_API_KEY does not start with 'sk-ant-'. Check you copied the whole key.")
    else:
        report(OK, "ANTHROPIC_API_KEY is set")

    if os.environ.get("ANTHROPIC_BASE_URL"):
        report(WARN, f"ANTHROPIC_BASE_URL is set to {os.environ['ANTHROPIC_BASE_URL']}; requests go there, "
                     "not to Anthropic.", "Remove it from your environment unless you meant to use a proxy.")

    for tier in ("report", "fast", "simulation"):
        report(OK, f"{tier:<10} model: {Config.claude_model(tier)} (effort {Config.claude_effort(tier) or 'default'})")
    report(OK, f"Budget R{Config.RUN_BUDGET_ZAR:.0f} per run (R{Config.REPORT_RESERVE_ZAR:.0f} kept for the report), "
               f"at R{Config.USD_ZAR_RATE} to the dollar")

    import anthropic

    client = anthropic.Anthropic(api_key=key, max_retries=1)
    for tier in ("fast", "report"):
        model = Config.claude_model(tier)
        try:
            response = client.messages.create(
                model=model, max_tokens=16000, output_config={"effort": "low"},
                messages=[{"role": "user", "content": "Reply with the single word: ready"}],
            )
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            report(OK, f"Claude answered on {model}: \"{text[:40]}\"")
        except anthropic.AuthenticationError:
            report(FAIL, "Anthropic rejected the API key.", "Create a new key at platform.claude.com and paste it again.")
            break
        except anthropic.PermissionDeniedError as error:
            report(FAIL, f"The key may not use {model}: {error.message}",
                   f"Check your Anthropic plan, or set CLAUDE_{tier.upper()}_MODEL to a model you can use.")
        except anthropic.RateLimitError:
            report(FAIL, "Anthropic says you are out of credit or over your rate limit.",
                   "Add credit at platform.claude.com (Settings > Billing).")
            break
        except anthropic.APIConnectionError:
            report(FAIL, "Could not reach api.anthropic.com.", "Check your internet connection or firewall.")
            break
        except anthropic.APIStatusError as error:
            report(FAIL, f"Anthropic returned {error.status_code}: {error.message}")
            break

    zep = Config.ZEP_API_KEY or ""
    if placeholder(zep):
        report(WARN, "No ZEP_API_KEY: simulations and the God View work, but building graphs from documents and "
                     "generating reports need Zep.", "Free key at app.getzep.com; put it in .env as ZEP_API_KEY.")
    else:
        try:
            from zep_cloud.client import Zep

            Zep(api_key=zep).graph.list_all(page_size=1)
            report(OK, "Zep key works")
        except Exception as error:  # report any Zep failure in plain words
            report(FAIL, f"Zep rejected the key or could not be reached: {str(error)[:120]}",
                   "Check ZEP_API_KEY at app.getzep.com.")

    return finish()


def finish():
    print()
    if problems:
        print(f"{problems} problem(s) to fix. Run `npm run check` again afterwards.")
        return 1
    print("Ready. Start MiroFish with `npm run dev` and open http://localhost:3000")
    print("Stress-tests: cd backend && uv run python ../sales_engine/stress_test.py --help")
    return 0


if __name__ == "__main__":
    sys.exit(main())
