# Multi-stage build per ottimizzazione
FROM python:3.11-slim as builder

# Installa dipendenze di build
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Crea virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Installa dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Stage finale - runtime
FROM python:3.11-slim

# Metadata
LABEL maintainer="MetalCoder <fabio@metalcoder.dev>"
LABEL description="Crypto Alert Telegram Bot - Production Ready"
LABEL version="1.0"

# Crea utente non-root per sicurezza
RUN groupadd -r botuser && useradd -r -g botuser -s /bin/false botuser

# Installa solo runtime essenziali
RUN apt-get update && apt-get install -y \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copia virtual environment dal builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Imposta working directory
WORKDIR /app

# Copia codice applicazione
COPY --chown=botuser:botuser . .

# Crea directory per database e logs
RUN mkdir -p /app/data /app/logs && \
    chown -R botuser:botuser /app/data /app/logs

# Variabili ambiente per production
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DB_PATH=/app/data/subs.db
ENV LOG_LEVEL=INFO

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5)" || exit 1

# Esponi porta per health check (opzionale)
EXPOSE 8000

# Cambia a utente non-root
USER botuser

# Punto di ingresso con gestione segnali
ENTRYPOINT ["python", "-u", "bot.py"]

# Comando di default
CMD []