# Tablero web del Huerto Inteligente. Multi-arquitectura (arm64 en la Pi, amd64 en PC).
# Se construye desde central/ (contexto) para incluir el paquete comun/.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY web/requirements.txt .
RUN pip install -r requirements.txt

COPY comun/ comun/
COPY web/web/ web/
# La API HTTP usa la misma validación que el procesador (procesador/ingreso.py)
COPY procesador/procesador/ procesador/
# Para aplicar migraciones dentro del contenedor (python -m comun.migrar)
COPY db/ db/

# Con carpeta personal: gunicorn guarda ahí su socket de control
RUN useradd --system --create-home huerto
USER huerto

EXPOSE 8080
# 1 proceso (el difusor MQTT -> SSE vive en memoria) con varios hilos:
# cada pantalla o celular abierto ocupa un hilo con su conexión SSE.
CMD ["gunicorn", "--workers", "1", "--threads", "32", "--bind", "0.0.0.0:8080", \
     "--access-logfile", "-", "web:crear_app()"]
