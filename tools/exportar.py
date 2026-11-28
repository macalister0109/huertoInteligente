"""Exporta los datos del huerto para análisis (CSV estándar y Parquet).

    python tools/exportar.py --desde 2026-11-01 --hasta 2026-11-30
    python tools/exportar.py --desde 2026-11-01 --hasta 2026-11-30 --cama 1 --formato parquet
    python tools/exportar.py --desde ... --hasta ... --conjuntos lecturas clima

Escribe una carpeta tools/salidas/exportacion_<desde>_<hasta>/ con un archivo
por conjunto: lecturas, agregados_hora, agregados_dia, eventos_riego, alertas
y clima. Usa la BD de central/.env (fuera de Docker: DB_HOST=127.0.0.1).

Parquet necesita pandas y pyarrow:  pip install -r analisis/requirements.txt
Significado de cada columna: docs/diccionario_de_datos.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "central"))

from comun.analitica import exportacion  # noqa: E402

COLUMNAS_FECHA = {"medido_en_utc", "recibido_en_utc", "hora_inicio_utc", "inicio_utc", "fin_utc",
                  "iniciada_en_utc", "actualizada_en_utc", "resuelta_en_utc", "observado_en_utc"}


def escribir_parquet(conjunto: str, filas: list[dict], destino: Path) -> int:
    try:
        import pandas as pd
    except ImportError as e:
        raise SystemExit("Parquet necesita pandas y pyarrow: pip install -r analisis/requirements.txt") from e
    df = pd.DataFrame(filas, columns=exportacion.COLUMNAS[conjunto])
    for columna in COLUMNAS_FECHA & set(df.columns):
        df[columna] = pd.to_datetime(df[columna], utc=True)
    if "fecha" in df.columns:
        df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    df.to_parquet(destino, index=False)
    return len(df)


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--desde", required=True, type=date.fromisoformat, help="AAAA-MM-DD (hora de Chile)")
    a.add_argument("--hasta", required=True, type=date.fromisoformat, help="AAAA-MM-DD (incluido)")
    a.add_argument("--cama", type=int, help="id de la cama (por defecto, todas)")
    a.add_argument("--formato", choices=("csv", "parquet", "ambos"), default="ambos")
    a.add_argument("--conjuntos", nargs="+", choices=exportacion.CONJUNTOS, default=list(exportacion.CONJUNTOS))
    a.add_argument("--salida", type=Path, help="carpeta de salida")
    args = a.parse_args(argv)
    if args.hasta < args.desde:
        a.error("--hasta debe ser igual o posterior a --desde")

    from comun.config import Config, cargar_env
    from comun.db import conectar

    cargar_env()
    cfg = Config.desde_entorno()
    zona = ZoneInfo(cfg.zona_horaria)
    carpeta = args.salida or RAIZ / "tools" / "salidas" / f"exportacion_{args.desde}_{args.hasta}"
    carpeta.mkdir(parents=True, exist_ok=True)
    conn = conectar(cfg)
    try:
        for conjunto in args.conjuntos:
            filas = list(exportacion.filas(conn, conjunto, args.desde, args.hasta, zona, args.cama))
            if args.formato in ("csv", "ambos"):
                exportacion.escribir_csv(conjunto, filas, carpeta / f"{conjunto}.csv")
            if args.formato in ("parquet", "ambos"):
                escribir_parquet(conjunto, filas, carpeta / f"{conjunto}.parquet")
            print(f"{conjunto:15} {len(filas):>8} filas")
    finally:
        conn.close()
    print(f"Listo: {carpeta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
