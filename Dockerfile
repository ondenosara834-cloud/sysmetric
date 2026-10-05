FROM python:3.12-slim AS base

# Pas de fichiers .pyc, logs affichés immédiatement
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# apt-get upgrade : applique les correctifs de sécurité Debian sortis depuis
#   la publication de l'image python:3.12-slim (failles détectées par Trivy).
# procps fournit la commande "uptime" utilisée par le collector.
# --no-install-recommends + nettoyage du cache apt = image plus petite,
# donc moins de paquets potentiellement vulnérables.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# 1) Installation des dépendances (timeout 120 s + 10 essais : connexion lente)
# 2) Suppression de pip : il embarque ses propres copies de msgpack, setuptools
#    et urllib3 (dossier pip/_vendor) signalées vulnérables par Trivy.
#    L'application n'a pas besoin de pip pour tourner : on l'enlève de l'image.
RUN pip install --no-cache-dir --default-timeout=120 --retries 10 -r requirements.txt \
    && pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip

COPY app/ ./app/

# Sécurité : on n'exécute pas l'application en root
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS agent

# L'agent n'expose pas d'API : on désactive le healthcheck hérité
HEALTHCHECK NONE

CMD ["python", "-m", "app.agent"]
