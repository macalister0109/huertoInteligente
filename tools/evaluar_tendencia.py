"""Evalúa la predicción de secado con los datos históricos (CQ-10 a CQ-13).

    python tools/evaluar_tendencia.py                         # BD de central/.env, todas las camas
    python tools/evaluar_tendencia.py --cama 1 --desde 2026-11-01 --hasta 2026-11-30
    python tools/evaluar_tendencia.py --csv lecturas.csv --minimo 30   # exportación o sintéticos

Qué hace (detalle en central/comun/analitica/evaluacion.py):
* Backtesting con ventana deslizante: en cada instante t (cada 30 min) el
  modelo usa SOLO datos ≤ t y se compara con el momento real del cruce del
  mínimo de humedad (CQ-12).
* MAE del tiempo hasta el mínimo con horizonte de 6 h (meta CQ-10: ≤ 2 h).
* Comparación con una referencia ingenua: tasa de secado promedio histórica
  constante (CQ-11).
* Tiempo de cálculo de cada predicción (CQ-13: ≤ 1 s; aquí sin la lectura de
  la BD, que el procesador mide aparte en la tabla tiempos_tendencia).

Escribe reportes/AAAA-MM-DD_evaluacion_tendencia.md y .csv. Si hay pocos
casos, lo dice y NO inventa métricas.

El CSV de entrada necesita las columnas medido_en (ISO, UTC) y suelo_prom; si
trae cama o cama_id, se evalúa cada cama por separado; si trae origen, se
informa (los datos sintéticos NUNCA se mezclan con los reales en el reporte).
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "central"))

from comun.analitica.calidad import excluidas  # noqa: E402
from comun.analitica.evaluacion import META_MAE_H, MIN_CASOS, Resultado, evaluar_cama  # noqa: E402
from comun.analitica.prediccion import ParametrosPrediccion  # noqa: E402
from comun.analitica.riego import Punto  # noqa: E402

CARPETA_REPORTES = RAIZ / "reportes"


# ------------------------------------------------------------------ datos

def desde_bd(cama_id, desde, hasta):
    """[(nombre, puntos, mínimo, riegos manuales)] desde la BD de central/.env."""
    from comun import ajustes
    from comun.analitica import repositorio as repo
    from comun.analitica.servicio_tendencia import parametros
    from comun.config import Config, cargar_env
    from comun.db import conectar
    from comun.rangos import rango_efectivo

    cargar_env()
    cfg = Config.desde_entorno()
    conn = conectar(cfg)
    try:
        p = parametros(cfg, ajustes.leer(conn, cfg))
        series = []
        for cama in repo.camas(conn, cama_id):
            minimo = rango_efectivo(cama).humedad_min
            lecturas = repo.lecturas_entre(conn, cama["id"], desde, hasta)
            fuera = excluidas(repo.marcas_entre(conn, cama["id"], desde, hasta))
            puntos = [Punto(l.id, l.medido_en, l.suelo) for l in lecturas
                      if l.suelo is not None and (l.id, "suelo") not in fuera]
            manuales = [e for e in repo.riegos(conn, cama["id"], desde, hasta) if e.origen == "manual"]
            series.append((cama["nombre"], puntos, minimo, manuales))
        conn.commit()
        return series, p, "base de datos (lecturas reales)"
    finally:
        conn.close()


def desde_csv(ruta: Path, minimo: float | None):
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))
    if not filas:
        return [], ParametrosPrediccion(), f"{ruta.name} (vacío)"
    origenes = {(f.get("origen") or "real").strip() for f in filas}
    if len(origenes) > 1:
        raise SystemExit("El CSV mezcla datos reales y sintéticos: evalúalos por separado.")
    por_cama: dict[str, list[Punto]] = {}
    minimos: dict[str, float] = {}
    for i, f in enumerate(filas):
        if not f.get("suelo_prom"):
            continue
        cama = f.get("cama") or f.get("cama_id") or "cama"
        t = datetime.fromisoformat(f["medido_en"].replace("Z", "+00:00"))
        if t.tzinfo is not None:
            t = t.astimezone(timezone.utc).replace(tzinfo=None)
        por_cama.setdefault(cama, []).append(Punto(i, t, float(f["suelo_prom"])))
        if f.get("humedad_min"):
            minimos[cama] = float(f["humedad_min"])
    series = [(c, pts, minimo if minimo is not None else minimos.get(c), [])
              for c, pts in sorted(por_cama.items())]
    return series, ParametrosPrediccion(), f"{ruta.name} (origen: {origenes.pop()})"


# ----------------------------------------------------------------- reporte

def _h(x):
    return "—" if x is None else f"{x:.2f} h".replace(".", ",")


def escribir_reporte(r: Resultado, fuente: str, p: ParametrosPrediccion, saltadas: list[str],
                     hoy: date, carpeta: Path = CARPETA_REPORTES) -> tuple[Path, Path]:
    carpeta.mkdir(parents=True, exist_ok=True)
    base = carpeta / f"{hoy.isoformat()}_evaluacion_tendencia"
    md, archivo_csv = base.with_suffix(".md"), base.with_suffix(".csv")

    with archivo_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cama", "t_utc", "valor", "minimo", "real_h", "modelo_estado", "modelo_h",
                    "ingenuo_h", "error_modelo_h", "error_ingenuo_h", "comparable"])
        for c in r.casos:
            w.writerow([c.cama, c.t.isoformat(), c.valor, c.minimo, c.real_h, c.modelo_estado,
                        c.modelo_h, c.ingenuo_h, c.error_modelo, c.error_ingenuo, int(c.comparable)])

    sin_prediccion = sum(1 for c in r.casos if c.modelo_h is None)
    tiempos = r.tiempos_ms
    lineas = [
        f"# Evaluación de la predicción de secado — {hoy.isoformat()}",
        "",
        f"- **Datos:** {fuente}",
        f"- **Camas evaluadas:** {', '.join(r.camas) or 'ninguna'}"
        + (f" · sin mínimo de humedad (no evaluadas): {', '.join(saltadas)}" if saltadas else ""),
        f"- **Parámetros:** ventana {p.ventana_h:g} h · mínimo {p.min_puntos} puntos · "
        f"R² ≥ {p.r2_min:g} · horizonte {p.horizonte_h:g} h · riego +{p.riego_umbral_pts:g} pts "
        f"en {p.riego_ventana_min:g} min",
        f"- **Método:** backtesting con ventana deslizante cada 30 min; en cada instante el modelo y la "
        "referencia usan solo datos anteriores (CQ-12).",
        "",
        "## Casos",
        "",
        f"| Instantes revisados | Casos con cruce real ≤ {p.horizonte_h:g} h | Sin predicción del modelo "
        "(«Sin tendencia clara») | Comparables (modelo y referencia) |",
        "| --- | --- | --- | --- |",
        f"| {r.instantes} | {len(r.casos)} | {sin_prediccion} | {len(r.comparables)} |",
        "",
        f"Avisos del modelo sin cruce real en {p.horizonte_h:g} h (posibles falsas alarmas): "
        f"**{r.avisos_sin_cruce}**.",
        "",
    ]
    if not r.suficiente:
        lineas += [
            "## Resultado",
            "",
            f"**Datos insuficientes:** hay {len(r.comparables)} casos comparables y se necesitan al "
            f"menos {MIN_CASOS}. No se calculan el MAE ni la comparación para no informar métricas "
            "sin respaldo. Hace falta juntar más días de lecturas con riegos y secados completos.",
            "",
        ]
    else:
        lineas += [
            "## Resultado",
            "",
            "| Métrica | Modelo (regresión del tramo) | Referencia ingenua (tasa promedio) |",
            "| --- | --- | --- |",
            f"| MAE del tiempo hasta el mínimo | {_h(r.mae_modelo)} | {_h(r.mae_ingenuo)} |",
            "",
            f"- **CQ-10 (MAE ≤ {META_MAE_H:g} h):** {'cumple' if r.cumple_meta else 'NO cumple'}.",
            f"- **CQ-11 (supera a la referencia):** {'sí' if r.supera_referencia else 'no'}.",
            "",
        ]
    if tiempos:
        lineas += [
            f"- **CQ-13 (cálculo ≤ 1 s por cama):** promedio {statistics.fmean(tiempos):.1f} ms, "
            f"máximo {max(tiempos):.1f} ms en este equipo (solo el cálculo; el procesador registra el "
            "tiempo total en la Raspberry Pi en la tabla `tiempos_tendencia`).",
            "",
        ]
    lineas += [f"Detalle de cada caso: `{archivo_csv.name}`.", ""]
    md.write_text("\n".join(lineas), encoding="utf-8")
    return md, archivo_csv


def main(argv=None) -> int:
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--csv", type=Path, help="lecturas exportadas o sintéticas (en vez de la BD)")
    a.add_argument("--minimo", type=float, help="mínimo de humedad (%%) para el CSV")
    a.add_argument("--cama", type=int, help="id de la cama (BD)")
    a.add_argument("--desde", type=date.fromisoformat, help="AAAA-MM-DD (BD)")
    a.add_argument("--hasta", type=date.fromisoformat, help="AAAA-MM-DD (BD)")
    a.add_argument("--salida", type=Path, default=CARPETA_REPORTES)
    args = a.parse_args(argv)

    if args.csv:
        series, p, fuente = desde_csv(args.csv, args.minimo)
    else:
        desde = datetime.combine(args.desde or date(2000, 1, 1), datetime.min.time())
        hasta = datetime.combine(args.hasta or date(2100, 1, 1), datetime.min.time()) + timedelta(days=1)
        try:
            series, p, fuente = desde_bd(args.cama, desde, hasta)
        except Exception as e:                      # BD sin migrar o apagada
            if getattr(e, "args", [None])[0] == 1146:
                print("A la BD le faltan las tablas nuevas. Aplica las migraciones:\n"
                      "    docker compose exec web python -m comun.migrar")
                return 2
            raise

    total, saltadas = Resultado(), []
    for nombre, puntos, minimo, manuales in series:
        if minimo is None:
            saltadas.append(nombre)
            continue
        total.sumar(evaluar_cama(nombre, puntos, minimo, p, riegos_conocidos=manuales))

    md, archivo_csv = escribir_reporte(total, fuente, p, saltadas, date.today(), args.salida)
    if total.suficiente:
        print(f"MAE modelo {_h(total.mae_modelo)} · MAE referencia {_h(total.mae_ingenuo)} · "
              f"{len(total.comparables)} casos · supera la referencia: "
              f"{'sí' if total.supera_referencia else 'no'}")
    else:
        print(f"Datos insuficientes: {len(total.comparables)} casos comparables (se necesitan "
              f"{MIN_CASOS}). No se calcularon métricas.")
    print(f"Reporte: {md}\nCasos:   {archivo_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
