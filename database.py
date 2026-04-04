import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

DB_PATH = "pystreamflow.db"


def get_connection():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        print(f"Error conectando a DB: {e}")
        raise


def init_db():
    try:
        with get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transacciones (
                    id TEXT PRIMARY KEY,
                    tipo TEXT NOT NULL,
                    monto REAL NOT NULL,
                    categoria TEXT NOT NULL,
                    descripcion TEXT,
                    fecha TEXT NOT NULL,
                    moneda TEXT NOT NULL DEFAULT 'ARS',
                    user_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS presupuestos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    categoria TEXT NOT NULL,
                    limite REAL NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, categoria)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS metas_ahorro (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    nombre TEXT NOT NULL,
                    objetivo REAL NOT NULL,
                    ahorrado REAL DEFAULT 0,
                    fecha_limite TEXT,
                categoria TEXT,
                fecha_creacion TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS config (
                    user_id TEXT PRIMARY KEY,
                    moneda_activa TEXT DEFAULT 'ARS',
                    filtro_fecha_inicio TEXT,
                    filtro_fecha_fin TEXT,
                    tasa_cambio REAL DEFAULT 1000.0
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS categorias_custom (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT,
                    tipo TEXT NOT NULL,
                    nombre TEXT NOT NULL,
                    UNIQUE(user_id, tipo, nombre)
                )
            """)

            conn.commit()
    except sqlite3.Error as e:
        print(f"Error inicializando DB: {e}")
        raise


def get_user_id() -> str:
    import streamlit as st

    if st.session_state.get("logged_in") and st.session_state.get("user_id"):
        return st.session_state.user_id
    return "local"


def guardar_transaccion(transaccion: dict) -> bool:
    user_id = get_user_id()
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO transacciones 
                (id, tipo, monto, categoria, descripcion, fecha, moneda, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    transaccion.get("id"),
                    transaccion.get("tipo"),
                    transaccion.get("monto"),
                    transaccion.get("categoria"),
                    transaccion.get("descripcion", ""),
                    transaccion.get("fecha"),
                    transaccion.get("moneda", "ARS"),
                    user_id,
                ),
            )
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error guardando transacción: {e}")
        return False


def guardar_categoria_custom(tipo: str, categoria: str) -> bool:
    """Guarda una categoría custom del usuario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO categorias_custom (user_id, tipo, nombre)
                VALUES (?, ?, ?)
                """,
                (user_id, tipo, categoria),
            )
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error guardando categoría custom: {e}")
        return False


def cargar_categorias_custom() -> dict:
    """Carga las categorías custom del usuario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT tipo, nombre FROM categorias_custom 
                WHERE user_id = ? OR user_id = 'local'
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            resultado = {"Ingreso": [], "Gasto": []}
            for row in rows:
                if row["tipo"] in resultado:
                    resultado[row["tipo"]].append(row["nombre"])
            return resultado
    except sqlite3.Error as e:
        print(f"Error cargando categorías custom: {e}")
        return {"Ingreso": [], "Gasto": []}


def guardar_tasa_cambio(tasa: float) -> bool:
    """Guarda la tasa de cambio ARS/USD"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO config (user_id, tasa_cambio)
                VALUES (?, ?)
                """,
                (user_id, tasa),
            )
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error guardando tasa: {e}")
        return False


def cargar_tasa_cambio() -> float:
    """Carga la tasa de cambio guardada"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT tasa_cambio FROM config WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            row = cursor.fetchone()
            return float(row["tasa_cambio"]) if row and row["tasa_cambio"] else 1000.0
    except (sqlite3.Error, TypeError, ValueError) as e:
        print(f"Error cargando tasa: {e}")
        return 1000.0


def sincronizar_desde_supabase(transacciones: list, presupuestos: dict, metas: dict):
    for t in transacciones:
        guardar_transaccion(t)

    for cat, datos in presupuestos.items():
        guardar_presupuesto(cat, datos.get("limite", 0))

    for meta in metas.values():
        guardar_meta(meta)


def cargar_transacciones() -> list:
    """Carga todas las transacciones del usuario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM transacciones WHERE user_id = ? OR user_id = 'local' ORDER BY fecha DESC",
                (user_id,),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
    except sqlite3.Error as e:
        print(f"Error cargando transacciones: {e}")
        return []


def eliminar_transaccion(transaccion_id: str) -> bool:
    """Elimina una transacción por ID"""
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM transacciones WHERE id = ?", (transaccion_id,))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error eliminando transacción: {e}")
        return False


def guardar_presupuesto(categoria: str, limite: float) -> bool:
    """Guarda o actualiza un presupuesto por categoría"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO presupuestos (user_id, categoria, limite)
                VALUES (?, ?, ?)
                """,
                (user_id, categoria, limite),
            )
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error guardando presupuesto: {e}")
        return False


def cargar_presupuestos() -> dict:
    """Carga todos los presupuestos del usuario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT categoria, limite FROM presupuestos WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            rows = cursor.fetchall()
            return {row["categoria"]: {"limite": row["limite"]} for row in rows}
    except sqlite3.Error as e:
        print(f"Error cargando presupuestos: {e}")
        return {}


def guardar_meta(meta: dict) -> bool:
    """Guarda o actualiza una meta de ahorro"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO metas_ahorro 
                (id, user_id, nombre, objetivo, ahorrado, fecha_limite, categoria)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meta.get("id"),
                    user_id,
                    meta.get("nombre"),
                    meta.get("objetivo"),
                    meta.get("ahorrado", 0),
                    meta.get("fecha_limite"),
                    meta.get("categoria"),
                ),
            )
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error guardando meta: {e}")
        return False


def cargar_metas() -> dict:
    """Carga todas las metas de ahorro del usuario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM metas_ahorro WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            rows = cursor.fetchall()
            return {row["id"]: dict(row) for row in rows}
    except sqlite3.Error as e:
        print(f"Error cargando metas: {e}")
        return {}


def cargar_config() -> dict:
    """Carga la configuración del usuario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM config WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else {}
    except sqlite3.Error as e:
        print(f"Error cargando config: {e}")
        return {}


def guardar_config(moneda: str = None, fecha_inicio: str = None, fecha_fin: str = None) -> bool:
    """Guarda la configuración del usuario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO config (user_id, moneda_activa, filtro_fecha_inicio, filtro_fecha_fin)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, moneda, fecha_inicio, fecha_fin),
            )
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error guardando config: {e}")
        return False


def exportar_backup() -> dict:
    """Exporta todos los datos como diccionario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            cursor_t = conn.execute(
                "SELECT * FROM transacciones WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            transacciones = [dict(row) for row in cursor_t.fetchall()]

            cursor_p = conn.execute(
                "SELECT * FROM presupuestos WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            presupuestos = {row["categoria"]: dict(row) for row in cursor_p.fetchall()}

            cursor_m = conn.execute(
                "SELECT * FROM metas_ahorro WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            metas = {row["id"]: dict(row) for row in cursor_m.fetchall()}

            cursor_c = conn.execute(
                "SELECT * FROM config WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            configs = [dict(row) for row in cursor_c.fetchall()]

            cursor_cat = conn.execute(
                "SELECT * FROM categorias_custom WHERE user_id = ? OR user_id = 'local'",
                (user_id,),
            )
            categorias_custom = [dict(row) for row in cursor_cat.fetchall()]

        return {
            "transacciones": transacciones,
            "presupuestos": presupuestos,
            "metas_ahorro": metas,
            "config": configs,
            "categorias_custom": categorias_custom,
            "exported_at": datetime.now().isoformat(),
        }
    except sqlite3.Error as e:
        print(f"Error exportando backup: {e}")
        return {}


def importar_backup(data: dict, modo: str = "agregar") -> bool:
    """
    Importa datos desde un diccionario
    modo: "reemplazar" (borra datos actuales) o "agregar" (mantiene actuales)
    """
    try:
        user_id = get_user_id()

        if modo == "reemplazar":
            with get_connection() as conn:
                conn.execute("DELETE FROM transacciones WHERE user_id = ?", (user_id,))
                conn.execute("DELETE FROM presupuestos WHERE user_id = ?", (user_id,))
                conn.execute("DELETE FROM metas_ahorro WHERE user_id = ?", (user_id,))
                conn.commit()

        with get_connection() as conn:
            if "transacciones" in data:
                for t in data["transacciones"]:
                    t["user_id"] = user_id
                    guardar_transaccion(t)

            if "presupuestos" in data:
                for cat, datos in data["presupuestos"].items():
                    guardar_presupuesto(cat, datos.get("limite", 0))

            if "metas_ahorro" in data:
                for meta in data["metas_ahorro"].values():
                    meta["user_id"] = user_id
                    guardar_meta(meta)

            if "categorias_custom" in data:
                for cat in data["categorias_custom"]:
                    guardar_categoria_custom(cat["tipo"], cat["nombre"])

        return True
    except Exception as e:
        print(f"Error importando backup: {e}")
        return False


def eliminar_todas_transacciones() -> bool:
    """Elimina todas las transacciones del usuario"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            conn.execute("DELETE FROM transacciones WHERE user_id = ?", (user_id,))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error eliminando todas las transacciones: {e}")
        return False


def eliminar_presupuesto(categoria: str) -> bool:
    """Elimina un presupuesto por categoría"""
    try:
        user_id = get_user_id()
        with get_connection() as conn:
            conn.execute(
                "DELETE FROM presupuestos WHERE user_id = ? AND categoria = ?",
                (user_id, categoria),
            )
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error eliminando presupuesto: {e}")
        return False


def eliminar_meta(meta_id: str) -> bool:
    """Elimina una meta de ahorro por ID"""
    try:
        with get_connection() as conn:
            conn.execute("DELETE FROM metas_ahorro WHERE id = ?", (meta_id,))
            conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error eliminando meta: {e}")
        return False
