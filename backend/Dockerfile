# Eco-Code Profiler — backend (+ derlenmiş frontend) imajı.
# Derleme bağlamı proje kök dizinidir:
#   docker build -f backend/Dockerfile -t eco-profiler .

# --- 1) Frontend derlemesi ---------------------------------------------------
FROM node:22-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- 2) Backend çalışma imajı ----------------------------------------------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
# main.py, ../frontend/dist varsa onu kök adresten sunar.
COPY --from=frontend /src/frontend/dist /app/frontend/dist

# Kullanıcı kodu (verifier alt süreci) root olmayan bir kullanıcıyla çalışsın.
RUN useradd --create-home --uid 10001 eco
USER eco

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/patterns', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
