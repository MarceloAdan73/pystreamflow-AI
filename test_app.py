import pytest
import pandas as pd
from datetime import datetime, timedelta
from pystreamflow import (
    detectar_moneda,
    formatear_monto,
    calcular_metricas,
    Transaccion,
    generar_id,
    MONEDAS,
    COLORES,
)

# ============================
# TESTS DE DETECCIÓN DE MONTO
# ============================


def test_detectar_moneda_simple():
    """Test: Detectar monto simple"""
    monto, moneda = detectar_moneda("15000")
    assert monto == 15000
    assert moneda == "ARS"


def test_detectar_moneda_con_texto():
    """Test: Detectar monto con texto"""
    monto, moneda = detectar_moneda("15000 ARS")
    assert monto == 15000
    assert moneda == "ARS"


def test_detectar_moneda_con_comas():
    """Test: Números con comas (1,500)"""
    monto, moneda = detectar_moneda("1,500")
    assert monto == 1500
    assert moneda == "ARS"


def test_detectar_moneda_decimal():
    """Test: Números decimales"""
    monto, moneda = detectar_moneda("99.99")
    assert monto == 99.99
    assert moneda == "ARS"


def test_detectar_moneda_invalida():
    """Test: Texto sin números"""
    monto, moneda = detectar_moneda("hola mundo")
    assert monto is None
    assert moneda is None


def test_detectar_moneda_vacio():
    """Test: String vacío"""
    monto, moneda = detectar_moneda("")
    assert monto is None
    assert moneda is None


# ============================
# TESTS DE FORMATEO DE MONTO
# ============================


def test_formatear_monto_ars(monkeypatch):
    """Test: Formatear monto ARS"""
    resultado = formatear_monto(15000, "ARS")
    assert "$ 15,000" in resultado


def test_formatear_monto_decimal(monkeypatch):
    """Test: Formatear monto con decimales"""
    resultado = formatear_monto(99.99, "ARS")
    assert "$ 99.99" in resultado


# ============================
# TESTS DE CÁLCULO DE MÉTRICAS
# ============================


def test_calcular_metricas_vacio():
    """Test: DataFrame vacío"""
    df = pd.DataFrame()
    resultado = calcular_metricas(df)
    assert resultado["ingresos"] == 0
    assert resultado["gastos"] == 0
    assert resultado["balance"] == 0
    assert resultado["count"] == 0


def test_calcular_metricas_solo_ingresos():
    """Test: Solo ingresos"""
    data = [{"tipo": "Ingreso", "monto": 1000}, {"tipo": "Ingreso", "monto": 500}]
    df = pd.DataFrame(data)
    resultado = calcular_metricas(df)
    assert resultado["ingresos"] == 1500
    assert resultado["gastos"] == 0
    assert resultado["balance"] == 1500
    assert resultado["count"] == 2


def test_calcular_metricas_solo_gastos():
    """Test: Solo gastos"""
    data = [{"tipo": "Gasto", "monto": 300}, {"tipo": "Gasto", "monto": 200}]
    df = pd.DataFrame(data)
    resultado = calcular_metricas(df)
    assert resultado["ingresos"] == 0
    assert resultado["gastos"] == 500
    assert resultado["balance"] == -500
    assert resultado["count"] == 2


def test_calcular_metricas_mixto():
    """Test: Ingresos y gastos"""
    data = [
        {"tipo": "Ingreso", "monto": 1000},
        {"tipo": "Gasto", "monto": 300},
        {"tipo": "Ingreso", "monto": 500},
        {"tipo": "Gasto", "monto": 200},
    ]
    df = pd.DataFrame(data)
    resultado = calcular_metricas(df)
    assert resultado["ingresos"] == 1500
    assert resultado["gastos"] == 500
    assert resultado["balance"] == 1000
    assert resultado["count"] == 4


# ============================
# TESTS DE MODELO
# ============================


def test_crear_transaccion():
    """Test: Crear transacción con dataclass"""
    tx = Transaccion(
        id="test_123",
        tipo="Ingreso",
        monto=1000,
        categoria="Salario",
        descripcion="Test",
        fecha="2024-01-01",
        moneda="ARS",
    )
    assert tx.id == "test_123"
    assert tx.tipo == "Ingreso"
    assert tx.monto == 1000
    assert tx.categoria == "Salario"
    assert tx.moneda == "ARS"


def test_transaccion_to_dict():
    """Test: Convertir transacción a diccionario"""
    tx = Transaccion(
        id="test_123",
        tipo="Ingreso",
        monto=1000,
        categoria="Salario",
        descripcion="Test",
        fecha="2024-01-01",
        moneda="ARS",
    )
    dict_tx = tx.to_dict()
    assert dict_tx["id"] == "test_123"
    assert dict_tx["monto"] == 1000
    assert dict_tx["tipo"] == "Ingreso"


def test_generar_id_formato():
    """Test: Formato del ID generado"""
    id_generado = generar_id()
    assert id_generado.startswith("txn_")
    assert len(id_generado) > 20


# ============================
# TESTS DE INTEGRACIÓN BÁSICA
# ============================


def test_ciclo_completo_transaccion():
    """Test: Crear transacción y calcular métricas"""
    tx = Transaccion(
        id=generar_id(),
        tipo="Ingreso",
        monto=2500,
        categoria="Salario",
        descripcion="Sueldo",
        fecha=datetime.now().strftime("%Y-%m-%d"),
        moneda="ARS",
    )

    transacciones = [tx.to_dict()]
    df = pd.DataFrame(transacciones)
    metricas = calcular_metricas(df)

    assert metricas["ingresos"] == 2500
    assert metricas["gastos"] == 0
    assert metricas["balance"] == 2500
    assert metricas["count"] == 1


def test_formato_consistente():
    """Test: El formato de moneda es consistente"""
    monto, moneda = detectar_moneda("15000")
    assert moneda == "ARS"
    assert formatear_monto(monto, moneda) == "$ 15,000"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
