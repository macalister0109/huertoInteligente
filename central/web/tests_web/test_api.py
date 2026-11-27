"""API HTTP para los ESP32: POST /api/lecturas y GET /api/camas/<nodo_id>/ultima."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pruebas.bd import INICIO
from web import nodos

pytestmark = pytest.mark.bd

MIN = timedelta(minutes=1)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def lectura(seq: int = 15, medido_en: datetime = INICIO, **cambios) -> dict:
    """El JSON que envía el firmware (especificación del prompt)."""
    datos = {"nodo_id": "cama-a", "seq": seq, "medido_en": _iso(medido_en),
             "temp": 23, "hum_aire": 61, "suelo_pct": 42, "suelo_mv": 2350}
    datos.update(cambios)
    return datos


@pytest.fixture
def token(bd, datos):
    datos.cama("cama-a", "Cama A")
    return nodos.crear_nodo(bd, "cama-a")


@pytest.fixture
def enviar(cliente, token, reloj):
    def _enviar(*, con_token: str | None = token, llegada: datetime | None = None,
                crudo: bytes | None = None, **cambios):
        """Simula al ESP32. Por defecto la lectura llega 2 s después de medirse."""
        medido_en = cambios.get("medido_en", INICIO)
        reloj.t = llegada or (medido_en + timedelta(seconds=2))
        cabeceras = {"Authorization": f"Bearer {con_token}"} if con_token else {}
        if crudo is not None:
            return cliente.post("/api/lecturas", data=crudo, headers=cabeceras,
                                content_type="application/json")
        return cliente.post("/api/lecturas", json=lectura(**cambios), headers=cabeceras)
    return _enviar


def filas_lecturas(datos) -> list[dict]:
    return datos.consulta("SELECT * FROM lecturas ORDER BY id")


# ---------------------------------------------------------------------------
# Inserción
# ---------------------------------------------------------------------------

class TestInsercion:
    def test_guarda_la_lectura_y_responde_201(self, enviar, datos, difusor):
        r = enviar()
        assert r.status_code == 201
        assert r.get_json()["estado"] == "guardada"
        assert r.get_json()["valida"] is True

        fila, = filas_lecturas(datos)
        assert fila["seq"] == 15
        assert fila["medido_en"] == INICIO
        assert fila["recibido_en"] == INICIO + timedelta(seconds=2)
        assert fila["temp"] == 23 and fila["hum_aire"] == 61
        assert fila["suelo_prom"] == 42 and fila["suelo_mv"] == 2350
        assert fila["valida"] == 1 and fila["motivo_invalida"] is None
        # El procesador recibe el aviso para calcular alertas y estado
        assert difusor.avisos_lectura == [fila["id"]]

    def test_sensor_en_null_no_bloquea_a_los_demas(self, enviar, datos):
        r = enviar(temp=None, hum_aire=None)
        assert r.status_code == 201
        fila, = filas_lecturas(datos)
        assert fila["temp"] is None and fila["hum_aire"] is None
        assert fila["suelo_prom"] == 42 and fila["valida"] == 1

    def test_registra_el_ultimo_uso_del_token(self, enviar, datos):
        enviar()
        nodo, = datos.consulta("SELECT ultimo_uso_en FROM nodos")
        assert nodo["ultimo_uso_en"] == INICIO + timedelta(seconds=2)


# ---------------------------------------------------------------------------
# Duplicados (reenvío del buffer del ESP32)
# ---------------------------------------------------------------------------

class TestDuplicado:
    def test_mismo_seq_y_hora_responde_200_y_no_duplica(self, enviar, datos, difusor):
        assert enviar(seq=7).status_code == 201
        r = enviar(seq=7)
        assert r.status_code == 200
        assert r.get_json()["estado"] == "duplicada"
        assert len(filas_lecturas(datos)) == 1
        assert len(difusor.avisos_lectura) == 1

    def test_mismo_seq_con_otra_hora_responde_409(self, enviar, datos):
        assert enviar(seq=7).status_code == 201
        r = enviar(seq=7, medido_en=INICIO + 60 * MIN)
        assert r.status_code == 409
        assert len(filas_lecturas(datos)) == 1
        assert datos.consulta("SELECT tipo FROM incidencias") == [{"tipo": "seq_reiniciado"}]


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

class TestToken:
    def test_sin_token_responde_401(self, enviar, datos):
        r = enviar(con_token=None)
        assert r.status_code == 401
        assert r.headers["WWW-Authenticate"].startswith("Bearer")
        assert filas_lecturas(datos) == []

    def test_token_invalido_responde_401(self, enviar, datos):
        assert enviar(con_token="no-es-el-token").status_code == 401
        assert filas_lecturas(datos) == []

    def test_token_de_nodo_desactivado_responde_401(self, enviar, datos, bd):
        datos.consulta("UPDATE nodos SET activo = 0")
        assert enviar().status_code == 401

    def test_token_de_otro_nodo_responde_403(self, enviar, datos):
        r = enviar(nodo_id="cama-b")
        assert r.status_code == 403
        assert filas_lecturas(datos) == []

    def test_el_token_no_se_guarda_en_texto_plano(self, token, datos):
        nodo, = datos.consulta("SELECT token_hash FROM nodos")
        assert token not in nodo["token_hash"]
        assert nodo["token_hash"] == nodos.hash_token(token)

    def test_regenerar_invalida_el_token_anterior(self, enviar, token, bd):
        nuevo = nodos.crear_nodo(bd, "cama-a", regenerar=True)
        assert enviar(con_token=token).status_code == 401
        assert enviar(con_token=nuevo).status_code == 201

    def test_crear_dos_veces_sin_regenerar_falla(self, token, bd):
        with pytest.raises(nodos.NodoYaExiste):
            nodos.crear_nodo(bd, "cama-a")


# ---------------------------------------------------------------------------
# JSON mal formado
# ---------------------------------------------------------------------------

class TestJsonMalFormado:
    @pytest.mark.parametrize("crudo", [b"{no es json", b"[1, 2]", b'{"seq": 1}',
                                       b'{"seq": "uno", "medido_en": "2026-11-26T15:00:00Z"}',
                                       b'{"seq": 1, "medido_en": "ayer"}'])
    def test_responde_400(self, enviar, datos, crudo):
        r = enviar(crudo=crudo)
        assert r.status_code == 400
        assert filas_lecturas(datos) == []
        assert datos.consulta("SELECT tipo FROM incidencias") == [{"tipo": "mensaje_invalido"}]


# ---------------------------------------------------------------------------
# Valores fuera de rango: se guardan como inválidos, no se rechazan
# ---------------------------------------------------------------------------

class TestFueraDeRango:
    def test_temperatura_sobre_50_se_guarda_marcada(self, enviar, datos):
        r = enviar(temp=85)
        assert r.status_code == 201
        assert r.get_json()["campos_invalidos"] == ["temp"]
        fila, = filas_lecturas(datos)
        assert fila["temp"] is None          # no se usa para alertas ni gráficos
        assert fila["valida"] == 1           # el resto de la lectura sirve
        assert "temp fuera de rango físico (85)" in fila["motivo_invalida"]

    def test_temperatura_bajo_cero_es_imposible_para_el_dht11(self, enviar, datos):
        assert enviar(temp=-3).status_code == 201
        fila, = filas_lecturas(datos)
        assert fila["temp"] is None
        assert "temp fuera de rango físico (-3)" in fila["motivo_invalida"]

    def test_todos_los_valores_imposibles_guarda_lectura_invalida(self, enviar, datos):
        r = enviar(temp=99, hum_aire=140, suelo_pct=130, suelo_mv=9000)
        assert r.status_code == 201
        assert r.get_json()["valida"] is False
        fila, = filas_lecturas(datos)
        assert fila["valida"] == 0
        assert fila["motivo_invalida"].startswith("sin datos válidos")


# ---------------------------------------------------------------------------
# GET /api/camas/<nodo_id>/ultima (HU-01)
# ---------------------------------------------------------------------------

class TestUltima:
    def test_sin_lecturas(self, cliente, token):
        r = cliente.get("/api/camas/cama-a/ultima")
        assert r.status_code == 200
        assert r.get_json()["mensaje"] == "Sin lecturas"
        assert r.get_json()["lectura"] is None

    def test_nodo_desconocido_responde_404(self, cliente):
        assert cliente.get("/api/camas/cama-z/ultima").status_code == 404

    def test_devuelve_la_lectura(self, cliente, enviar):
        enviar()
        r = cliente.get("/api/camas/cama-a/ultima").get_json()
        assert r["mensaje"] is None
        assert r["cama"] == "Cama A"
        assert r["lectura"] == {"seq": 15, "medido_en": "2026-11-26T15:00:00Z",
                                "recibido_en": "2026-11-26T15:00:02Z", "temp": 23.0,
                                "hum_aire": 61.0, "suelo_pct": 42.0, "suelo_mv": 2350, "luz": None}

    def test_lectura_atrasada_no_reemplaza_a_la_actual(self, cliente, enviar):
        """HU-01, criterio 2: manda la de mayor medido_en, no la última en llegar."""
        enviar(seq=2, medido_en=INICIO + 10 * MIN, suelo_pct=40)
        # Llega después, pero se midió antes (venía del buffer)
        r = enviar(seq=1, medido_en=INICIO, suelo_pct=65, llegada=INICIO + 12 * MIN)
        assert r.status_code == 201
        ultima = cliente.get("/api/camas/cama-a/ultima").get_json()["lectura"]
        assert ultima["seq"] == 2
        assert ultima["suelo_pct"] == 40.0

    def test_ignora_las_lecturas_invalidas(self, cliente, enviar):
        enviar(seq=1, medido_en=INICIO, suelo_pct=40)
        enviar(seq=2, medido_en=INICIO + MIN, temp=99, hum_aire=140, suelo_pct=130, suelo_mv=9000)
        assert cliente.get("/api/camas/cama-a/ultima").get_json()["lectura"]["seq"] == 1


# ---------------------------------------------------------------------------
# Detrás de nginx (servidor): la IP real llega en X-Forwarded-For
# ---------------------------------------------------------------------------

class TestDetrasDeProxy:
    def _app(self, difusor, reloj, saltos: int):
        from comun.db import conectar
        from pruebas.bd import CFG
        from web import crear_app
        from web.config import ConfigWeb

        cfg = ConfigWeb(bd=CFG, pin_docente="2468", clave_sesion="x", proxy_saltos=saltos,
                        cookie_segura=bool(saltos))
        app = crear_app(cfg, difusor=difusor, conectar_bd=lambda: conectar(CFG), reloj=reloj)

        @app.get("/_ip")
        def _ip():
            from flask import request
            return {"ip": request.remote_addr, "https": request.scheme == "https"}
        return app

    def test_con_proxy_usa_la_ip_del_visitante(self, bd, difusor, reloj):
        cliente = self._app(difusor, reloj, saltos=1).test_client()
        r = cliente.get("/_ip", headers={"X-Forwarded-For": "200.1.2.3",
                                         "X-Forwarded-Proto": "https"}).get_json()
        assert r == {"ip": "200.1.2.3", "https": True}

    def test_sin_proxy_no_se_cree_la_cabecera(self, bd, difusor, reloj):
        """En la casa nadie puede hacerse pasar por otra IP para saltarse el bloqueo del PIN."""
        cliente = self._app(difusor, reloj, saltos=0).test_client()
        r = cliente.get("/_ip", headers={"X-Forwarded-For": "200.1.2.3"}).get_json()
        assert r["ip"] == "127.0.0.1" and r["https"] is False

    def test_cookie_segura_en_el_servidor(self, bd, difusor, reloj):
        app = self._app(difusor, reloj, saltos=1)
        assert app.config["SESSION_COOKIE_SECURE"] is True
