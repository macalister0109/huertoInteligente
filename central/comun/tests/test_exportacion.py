"""Exportación para análisis, datos sintéticos y regla de no mezclar orígenes."""

import csv
import io
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from comun.analitica import exportacion
from comun.analitica.proceso import recalcular
from pruebas.bd import CFG

RAIZ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(RAIZ / "tools"))
ZONA = ZoneInfo("America/Santiago")
INICIO_DIA = datetime(2026, 11, 26, 3, 0)          # 00:00 en Chile


def leer_csv(conjunto, filas):
    texto = "".join(exportacion.csv_por_partes(conjunto, filas))
    return list(csv.DictReader(io.StringIO(texto)))


# ------------------------------------------------------- con la BD de test

@pytest.mark.bd
def test_exporta_lecturas_con_marcas_y_todos_los_conjuntos(bd):
    with bd.cursor() as cur:
        cur.execute("INSERT INTO camas (nombre, nodo_id, cultivo_id) VALUES "
                    "('Cama A', 'cama-a', (SELECT id FROM cultivos WHERE nombre = 'tomate')), "
                    "('Cama B', 'cama-b', NULL)")
        cur.execute("SELECT id, nombre FROM camas")
        ids = {f["nombre"]: f["id"] for f in cur.fetchall()}
        filas = []
        for nombre, cama in ids.items():
            for m in range(0, 24 * 60, 2):
                t = INICIO_DIA + timedelta(minutes=m)
                suelo = 42.0 if nombre == "Cama B" else 60 - m / 100
                filas.append((cama, m + 1, t, t, suelo, 20 + m % 3, 50 + m % 7))
        cur.executemany("""INSERT INTO lecturas (cama_id, seq, medido_en, recibido_en, suelo_prom, temp, hum_aire)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""", filas)
        cur.execute("""INSERT INTO clima_referencia (fuente, observado_en, obtenido_en, lat, lon, temp_aire_c)
                       VALUES ('open-meteo', %s, %s, -33.54, -70.64, 18.5)""", (INICIO_DIA, INICIO_DIA))
    bd.commit()
    dia = date(2026, 11, 26)
    recalcular(bd, CFG, dia, dia, INICIO_DIA + timedelta(days=2))

    lecturas = leer_csv("lecturas", exportacion.filas(bd, "lecturas", dia, dia, ZONA))
    assert len(lecturas) == 2 * 720
    assert list(lecturas[0]) == exportacion.COLUMNAS["lecturas"]
    assert lecturas[0]["origen"] == "real" and lecturas[0]["medido_en_utc"] == "2026-11-26T03:00:00Z"
    cama_b = [f for f in lecturas if f["cama"] == "Cama B"]
    assert all(f["excluir_suelo"] == "1" and "suelo:pegado" in f["marcas"] for f in cama_b)   # 42 fijo 24 h
    assert all(f["excluir_suelo"] == "0" for f in lecturas if f["cama"] == "Cama A")

    # Filtro por cama y por fechas (días en hora de Chile)
    solo_a = list(exportacion.filas(bd, "lecturas", dia, dia, ZONA, cama_id=ids["Cama A"]))
    assert {f["cama"] for f in solo_a} == {"Cama A"}
    assert list(exportacion.filas(bd, "lecturas", date(2026, 11, 27), date(2026, 11, 27), ZONA)) == []

    for conjunto in exportacion.CONJUNTOS:
        filas_ = leer_csv(conjunto, exportacion.filas(bd, conjunto, dia, dia, ZONA))
        assert all(f["origen"] == "real" for f in filas_)
    assert len(leer_csv("agregados_dia", exportacion.filas(bd, "agregados_dia", dia, dia, ZONA))) == 6
    assert leer_csv("clima", exportacion.filas(bd, "clima", dia, dia, ZONA))[0]["temp_aire_c"] == "18.5"


def test_conjunto_desconocido():
    with pytest.raises(ValueError):
        list(exportacion.filas(None, "otra", date(2026, 1, 1), date(2026, 1, 1), ZONA))


# --------------------------------------------------------- datos sintéticos

def test_sinteticos_reproducibles_y_marcados():
    import generar_sinteticos as g
    a = g.generar(date(2026, 10, 1), 3, semilla=5, intervalo_s=120)
    b = g.generar(date(2026, 10, 1), 3, semilla=5, intervalo_s=120)
    c = g.generar(date(2026, 10, 1), 3, semilla=6, intervalo_s=120)
    assert a == b                                           # misma semilla, mismos datos
    assert a["lecturas"] != c["lecturas"]
    for conjunto, filas in a.items():
        if not filas:
            continue
        assert {f["origen"] for f in filas} == {"sintetico"}
        assert list(leer_csv(conjunto, filas)[0]) == exportacion.COLUMNAS[conjunto]    # mismo formato


def test_sinteticos_traen_las_fallas_a_proposito():
    import generar_sinteticos as g
    datos = g.generar(date(2026, 10, 1), 14, semilla=2026, intervalo_s=120)
    marcas = {m for f in datos["lecturas"] if f["marcas"] for m in f["marcas"].split(";")}
    assert {"lectura:hueco", "suelo:pegado", "temp:rango", "hum_aire:salto"} <= marcas
    assert datos["eventos_riego"] and datos["alertas"] and datos["clima"]


def test_sinteticos_se_escriben_en_archivos_aparte(tmp_path):
    import generar_sinteticos as g
    assert g.CARPETA == RAIZ / "analisis" / "datos_sinteticos"
    g.main(["--dias", "2", "--intervalo", "300", "--salida", str(tmp_path)])
    assert {p.name for p in tmp_path.iterdir()} == {f"{c}.csv" for c in exportacion.CONJUNTOS} | {"LEEME.txt"}
    assert "SINTÉTICOS" in (tmp_path / "LEEME.txt").read_text(encoding="utf-8")


def test_la_evaluacion_rechaza_mezclar_reales_y_sinteticos(tmp_path):
    import evaluar_tendencia
    archivo = tmp_path / "mezcla.csv"
    archivo.write_text("medido_en,suelo_prom,origen\n2026-10-01T00:00:00Z,50,real\n"
                       "2026-10-01T00:01:00Z,50,sintetico\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="mezcla"):
        evaluar_tendencia.desde_csv(archivo, 30)
