# Procesador del Huerto Inteligente. Imagen multi-arquitectura (arm64 en la Pi, amd64 en PC).
# Se construye desde central/ (contexto) para incluir el paquete comun/.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY procesador/requirements.txt .
RUN pip install -r requirements.txt

COPY comun/ comun/
COPY procesador/procesador/ procesador/

# Sin privilegios de administrador
RUN useradd --system --no-create-home huerto
USER huerto

CMD ["python", "-m", "procesador.main"]
