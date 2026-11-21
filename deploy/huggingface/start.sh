#!/bin/bash
# Start MiroFish on Hugging Face Spaces.
set -e
cd /app/backend
# Zep is only needed to build worlds from uploaded documents. The app
# refuses to start without some value, so use a placeholder if unset.
export ZEP_API_KEY="${ZEP_API_KEY:-not-configured}"
if [ -z "$LLM_API_KEY" ] && [ "$LLM_PROVIDER" != "anthropic" ]; then
  echo "Set the Space secret LLM_API_KEY (your Groq key) and restart the Space." >&2
fi
if [ -z "$APP_PASSWORD" ]; then
  echo "WARNING: APP_PASSWORD is not set; anyone with the link can use this app and your API key." >&2
fi
# A ready-to-run world, so the God View has something to show on first visit.
if [ ! -f uploads/simulations/sim_tenderfind_live/state.json ]; then
  .venv/bin/python scripts/god_demo/make_tenderfind.py sim_tenderfind_live
fi
exec .venv/bin/python run.py
