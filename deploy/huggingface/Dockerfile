# MiroFish for Hugging Face Spaces (Docker SDK): one container, one port (7860).
# The backend serves the built website and the API; set the Space secrets
# LLM_API_KEY (your Groq key) and APP_PASSWORD (to keep the site private).

# --- website build (Vite 7 needs Node 20+) ---
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN npm ci --prefix frontend
COPY frontend ./frontend
COPY locales ./locales
RUN cd frontend && VITE_API_BASE_URL=/ npm run build

# --- app ---
FROM python:3.11
COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /uvx /bin/
RUN useradd -m -u 1000 user
WORKDIR /app
RUN chown user:user /app
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1

COPY --chown=user backend/pyproject.toml backend/uv.lock ./backend/
RUN cd backend && uv sync --frozen --no-install-project
COPY --chown=user . .
COPY --from=web --chown=user /web/frontend/dist ./frontend/dist

# Groq's free tier by default; LLM_API_KEY comes from the Space secret.
ENV FLASK_HOST=0.0.0.0 FLASK_PORT=7860 FRONTEND_DIST=/app/frontend/dist \
    LLM_PROVIDER=openai LLM_BASE_URL=https://api.groq.com/openai/v1 \
    LLM_MODEL_NAME=openai/gpt-oss-20b SIMULATION_LLM_CONCURRENCY=2

EXPOSE 7860
CMD ["bash", "deploy/huggingface/start.sh"]
