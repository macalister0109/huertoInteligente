"""Endpoint de tendencias con datos en la BD de test."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from comun.analitica.proceso import recalcular
from pruebas.bd import CFG, INICIO

pytestmark = pytest.mark.bd


def test_tendencia_de_una_cama_que_se_seca(cliente, datos, bd, reloj):
    cama = datos.cama("cama-a", "Cama A")
    # 30 h de datos, una lectura por minuto: el suelo baja 0,5 puntos por hora
    with bd.cursor() as cur:
        filas = []
        for m in range(30 * 60):
            t = INICIO - timedelta(minutes=30 * 60 - 1 - m)
            # 12-13 °C de noche y 22-23 °C de día (con variación: si no, sería «sensor pegado»)
            temp = 12 + 10 * (1 if 12 <= (t.hour - 3) % 24 <= 17 else 0) + m % 2
            filas.append((cama, m + 1, t, t, 70 - 0.5 * m / 60, temp, 50 + m % 9))
        cur.executemany("""INSERT INTO lecturas (cama_id, seq, medido_en, recibido_en, suelo_prom, temp, hum_aire)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""", filas)
        # Clima exterior de AYER, una instantánea por hora: entre 14 y 20 °C
        for h in range(24):
            t = INICIO - timedelta(hours=h + 9)
            cur.execute("""INSERT INTO clima_referencia (fuente, observado_en, obtenido_en, lat, lon, temp_aire_c)
                           VALUES ('open-meteo', %s, %s, -33.54, -70.64, %s)""", (t, t, 14 + (h % 7)))
    bd.commit()
    recalcular(bd, CFG, date(2026, 11, 25), date(2026, 11, 26), INICIO)

    d = cliente.get(f"/api/camas/{cama}/tendencia?horas=6").get_json()
    assert d["etiqueta"] == "Secándose lento"
    assert d["suelo"]["6h"]["pendiente_pts_h"] == pytest.approx(-0.5, abs=0.01)
    assert d["suelo"]["24h"]["etiqueta"] == "Secándose lento"
    assert d["suelo"]["6h"]["texto"] == "Secándose lento (−0,5 puntos por hora en las últimas 6 h)"
    assert 12 < d["media_movil_24h"]["temp"] < 23
    ayer = d["amplitud"]["ayer"]
    assert (ayer["cama_c"], ayer["exterior_c"], ayer["diferencia_c"]) == (11, 6, 5)
    assert "5 °C más que la zona" in ayer["texto"]
    assert len(d["serie_media_movil"]["temp"]) == 6


def test_tendencia_sin_datos(cliente, datos):
    cama = datos.cama("cama-a", "Cama A")
    d = cliente.get(f"/api/camas/{cama}/tendencia").get_json()
    assert d["etiqueta"] == "Sin datos suficientes"
    assert d["media_movil_24h"] == {"temp": None, "hum_aire": None}
    assert d["amplitud"] == {"ayer": None, "hoy": None}


def test_tendencia_de_cama_inexistente(cliente):
    assert cliente.get("/api/camas/9999/tendencia").status_code == 404


# ----------------------------------------------------- interfaz y configuración (etapa 7)

from .conftest import ingresar  # noqa: E402


def secado_con_riego(bd, cama):
    """6 h secándose 1 pt/h (hoy en 34 %) con un riego hace 8 h."""
    with bd.cursor() as cur:
        filas = []
        for m in range(10 * 60, -1, -1):
            t = INICIO - timedelta(minutes=m)
            suelo = 34 + m / 60 if m <= 8 * 60 - 20 else 25 + (m % 7) * 0.01
            filas.append((cama, 10 * 60 - m + 1, t, t, round(suelo, 2), 20 + m % 3, 50 + m % 5))
        cur.executemany("""INSERT INTO lecturas (cama_id, seq, medido_en, recibido_en, suelo_prom, temp, hum_aire)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""", filas)
    bd.commit()
    recalcular(bd, CFG, date(2026, 11, 26), date(2026, 11, 26), INICIO)


def test_serie_incluye_los_riegos_y_tendencia_la_recta(cliente, datos, bd):
    cama = datos.cama("cama-a", "Cama A")
    secado_con_riego(bd, cama)
    serie = cliente.get(f"/api/camas/{cama}/serie?horas=24").get_json()
    assert len(serie["riegos"]) == 1 and serie["riegos"][0]["despues"] > 40
    t = cliente.get(f"/api/camas/{cama}/tendencia").get_json()
    p = t["prediccion"]
    assert p["estado"] == "estimacion" and p["texto"].startswith("Al ritmo actual, la Cama A llegaría a 30 %")
    assert len(p["recta"]) == 2 and p["recta"][1]["valor"] == pytest.approx(30, abs=0.2)
    assert p["desde"] > serie["riegos"][0]["fin"]   # la recta empieza después del riego


def test_tendencias_para_las_tarjetas(cliente, datos, bd):
    cama = datos.cama("cama-a", "Cama A")
    secado_con_riego(bd, cama)
    d = cliente.get("/api/tendencias").get_json()
    assert d["camas"][0]["etiqueta"] == "Secándose lento"
    assert d["camas"][0]["estimacion"].startswith("Al ritmo actual")
    html = cliente.get(f"/cama/{cama}").get_data(as_text=True)
    assert 'id="panel-tendencia"' in html and "Tendencia del suelo" in html


def test_configuracion_de_tendencia(cliente, datos, bd):
    cama = datos.cama("cama-a", "Cama A")
    secado_con_riego(bd, cama)
    csrf = ingresar(cliente)
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert 'id="tendencia"' in html and 'name="tendencia_ventana_h"' in html and 'value="0.6"' in html
    # Activar la alerta, cambiar ventana, R² y el umbral de riego (se recalculan los riegos)
    r = cliente.post("/configuracion/tendencia", data={
        "csrf": csrf, "tendencia_ventana_h": "4", "tendencia_r2_min": "0,7", "riego_umbral_pts": "30",
        "tendencia_activa": ["0", "1"]})
    assert r.status_code == 302
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert "Ajustes de la tendencia guardados." in html
    assert "recalculados con el umbral nuevo: 0 encontrados" in html          # +30 no se alcanza
    from comun import ajustes
    bd.commit()                      # ver lo que guardó la web (otra conexión)
    v = ajustes.leer(bd, CFG)
    assert (v["tendencia_ventana_h"], v["tendencia_r2_min"], v["riego_umbral_pts"], v["tendencia_activa"]) == (
        4.0, 0.7, 30.0, True)
    # Desmarcar la casilla la desactiva
    cliente.post("/configuracion/tendencia", data={
        "csrf": csrf, "tendencia_ventana_h": "4", "tendencia_r2_min": "0.7", "riego_umbral_pts": "30",
        "tendencia_activa": "0"})
    bd.commit()
    assert ajustes.leer(bd, CFG)["tendencia_activa"] is False


def test_configuracion_de_tendencia_valida_los_valores(cliente):
    csrf = ingresar(cliente)
    cliente.post("/configuracion/tendencia", data={
        "csrf": csrf, "tendencia_ventana_h": "48", "tendencia_r2_min": "2", "riego_umbral_pts": "1"})
    html = cliente.get("/configuracion/").get_data(as_text=True)
    assert "entre 1 y 24" in html and "entre 0 y 1" in html and "entre 3 y 50" in html
