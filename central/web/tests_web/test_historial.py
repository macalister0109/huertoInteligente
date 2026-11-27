"""Historial: período de los gráficos, resumen por día y descarga CSV."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.bd

# 27-11-2026 15:00 UTC = 12:00 en Chile (UTC-3 en verano)
AHORA = datetime(2026, 11, 27, 15, 0, 0)


@pytest.fixture
def cama(datos, reloj):
    reloj.t = AHORA
    return datos.cama("cama-a", "Cama A")


def lectura_invalida(datos, cama_id: int, medido_en: datetime, seq: int) -> None:
    datos._ejecutar(
        """INSERT INTO lecturas (cama_id, seq, medido_en, recibido_en, temp, valida, motivo_invalida)
           VALUES (%s, %s, %s, %s, NULL, 0, 'sin datos válidos; temp fuera de rango físico (99)')""",
        (cama_id, seq, medido_en, medido_en))


# ---------------------------------------------------------------------------
# Resumen por día
# ---------------------------------------------------------------------------

class TestResumenDiario:
    def test_promedio_minimo_y_maximo_por_dia_de_chile(self, cliente, datos, cama):
        # 26-nov en Chile: 09:00, 18:00 y 23:30 (esta última ya es 27-nov en UTC)
        datos.lectura(cama, datetime(2026, 11, 26, 12, 0), 1, suelo=40, temp=20)
        datos.lectura(cama, datetime(2026, 11, 26, 21, 0), 2, suelo=60, temp=24)
        datos.lectura(cama, datetime(2026, 11, 27, 2, 30), 3, suelo=50, temp=22)
        # 27-nov en Chile: 09:00
        datos.lectura(cama, datetime(2026, 11, 27, 12, 0), 4, suelo=30, temp=18)

        r = cliente.get(f"/api/camas/{cama}/diario?dias=3").get_json()
        dias = {d["fecha"]: d for d in r["dias"]}
        assert [d["fecha"] for d in r["dias"]] == ["2026-11-27", "2026-11-26", "2026-11-25"]

        assert dias["2026-11-26"]["lecturas"] == 3
        assert dias["2026-11-26"]["suelo"] == {"prom": 50.0, "min": 40.0, "max": 60.0}
        assert dias["2026-11-26"]["temp"] == {"prom": 22.0, "min": 20.0, "max": 24.0}
        assert dias["2026-11-26"]["hum_aire"] == {"prom": 60.0, "min": 60.0, "max": 60.0}

        assert dias["2026-11-27"]["lecturas"] == 1
        assert dias["2026-11-27"]["suelo"]["prom"] == 30.0

        # Día sin datos: aparece, pero vacío (se nota el hueco)
        assert dias["2026-11-25"] == {"fecha": "2026-11-25", "lecturas": 0, "suelo": None,
                                      "temp": None, "hum_aire": None}

    def test_las_lecturas_invalidas_no_cuentan(self, cliente, datos, cama):
        datos.lectura(cama, datetime(2026, 11, 27, 12, 0), 1, suelo=30, temp=18)
        lectura_invalida(datos, cama, datetime(2026, 11, 27, 12, 1), 2)
        hoy = cliente.get(f"/api/camas/{cama}/diario?dias=1").get_json()["dias"][0]
        assert hoy["lecturas"] == 1 and hoy["temp"]["max"] == 18.0

    def test_limites_de_dias(self, cliente, cama):
        assert len(cliente.get(f"/api/camas/{cama}/diario?dias=0").get_json()["dias"]) == 1
        assert len(cliente.get(f"/api/camas/{cama}/diario?dias=5000").get_json()["dias"]) == 366

    def test_cama_desconocida(self, cliente):
        assert cliente.get("/api/camas/9999/diario").status_code == 404


# ---------------------------------------------------------------------------
# Gráficos: período de hasta 30 días
# ---------------------------------------------------------------------------

class TestPeriodoGraficos:
    @pytest.mark.parametrize("pedidas, usadas", [(24, 24), (168, 168), (720, 720), (5000, 720)])
    def test_horas(self, cliente, cama, pedidas, usadas):
        r = cliente.get(f"/api/camas/{cama}/serie?horas={pedidas}").get_json()
        desde = datetime.fromisoformat(r["desde"].replace("Z", ""))
        hasta = datetime.fromisoformat(r["hasta"].replace("Z", ""))
        assert hasta - desde == timedelta(hours=usadas)

    def test_30_dias_no_pasa_de_720_puntos(self, cliente, datos, cama):
        for i in range(0, 30 * 24 * 60, 20):          # una lectura cada 20 min durante 30 días
            datos.lectura(cama, AHORA - timedelta(minutes=i + 1), i + 1)
        puntos = cliente.get(f"/api/camas/{cama}/serie?horas=720").get_json()["puntos"]
        assert 0 < len(puntos) <= 720

    def test_pagina_de_detalle_tiene_periodos_y_descarga(self, cliente, cama):
        html = cliente.get(f"/cama/{cama}").get_data(as_text=True)
        assert 'data-horas="168"' in html and 'data-horas="720"' in html
        assert f'action="/cama/{cama}/lecturas.csv"' in html
        # Por defecto, los últimos 7 días en hora de Chile
        assert 'name="desde" value="2026-11-21"' in html
        assert 'name="hasta" value="2026-11-27"' in html


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

class TestCsv:
    def test_descarga_con_formato_para_excel(self, cliente, datos, cama):
        datos.lectura(cama, datetime(2026, 11, 26, 12, 0), 1, suelo=42.5, temp=23)
        lectura_invalida(datos, cama, datetime(2026, 11, 26, 12, 1), 2)

        r = cliente.get(f"/cama/{cama}/lecturas.csv?desde=2026-11-26&hasta=2026-11-26")
        assert r.status_code == 200
        assert r.mimetype == "text/csv"
        assert r.headers["Content-Disposition"] == \
            'attachment; filename="lecturas_cama-a_2026-11-26_2026-11-26.csv"'

        texto = r.get_data().decode("utf-8")
        assert texto.startswith("﻿")             # BOM: Excel ve bien los acentos
        lineas = texto.lstrip("﻿").splitlines()
        assert lineas[0] == ("fecha_hora_chile;fecha_hora_utc;seq;humedad_suelo_pct;suelo_mv;"
                             "temperatura_c;humedad_aire_pct;luz_lux;valida;motivo_invalida")
        # Hora de Chile (UTC-3), coma decimal y celdas vacías para lo que no hay
        assert lineas[1] == "2026-11-26 09:00:00;2026-11-26 12:00:00;1;42,5;;23;60;30000;sí;"
        # El motivo lleva ";" (el separador): va entre comillas para no partirse en dos columnas
        assert lineas[2] == ('2026-11-26 09:01:00;2026-11-26 12:01:00;2;;;;;;no;'
                             '"sin datos válidos; temp fuera de rango físico (99)"')
        assert len(lineas) == 3

    def test_las_fechas_son_dias_de_chile(self, cliente, datos, cama):
        datos.lectura(cama, datetime(2026, 11, 27, 2, 30), 1)   # 26-nov 23:30 en Chile
        datos.lectura(cama, datetime(2026, 11, 27, 3, 30), 2)   # 27-nov 00:30 en Chile
        r = cliente.get(f"/cama/{cama}/lecturas.csv?desde=2026-11-26&hasta=2026-11-26")
        lineas = r.get_data().decode("utf-8").lstrip("﻿").splitlines()
        assert len(lineas) == 2 and lineas[1].startswith("2026-11-26 23:30:00;2026-11-27 02:30:00;1;")

    def test_sin_fechas_son_los_ultimos_7_dias(self, cliente, cama):
        r = cliente.get(f"/cama/{cama}/lecturas.csv")
        assert 'filename="lecturas_cama-a_2026-11-21_2026-11-27.csv"' in r.headers["Content-Disposition"]

    @pytest.mark.parametrize("consulta", ["desde=ayer", "desde=2026-11-27&hasta=2026-11-20",
                                          "desde=2024-01-01&hasta=2026-11-27"])
    def test_fechas_invalidas(self, cliente, cama, consulta):
        assert cliente.get(f"/cama/{cama}/lecturas.csv?{consulta}").status_code == 400

    def test_cama_desconocida_o_inactiva(self, cliente, datos, cama):
        assert cliente.get("/cama/9999/lecturas.csv").status_code == 404
        inactiva = datos.cama("cama-z", "Cama Z", activa=0)
        assert cliente.get(f"/cama/{inactiva}/lecturas.csv").status_code == 404
