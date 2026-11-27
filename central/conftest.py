"""Fixtures comunes a todos los tests (procesador y web)."""

import pymysql
import pytest

from comun.db import conectar
from pruebas.bd import CFG, INICIO, MENSAJE_SIN_BD, Reloj, vaciar_bd


@pytest.fixture(scope="session")
def conexion_bd():
    try:
        conn = conectar(CFG)
    except pymysql.err.OperationalError as e:
        pytest.skip(MENSAJE_SIN_BD.format(e))
    yield conn
    conn.close()


@pytest.fixture
def bd(conexion_bd):
    """BD vacía (solo con las semillas) para cada test."""
    vaciar_bd(conexion_bd)
    return conexion_bd


@pytest.fixture
def reloj():
    return Reloj(INICIO)
