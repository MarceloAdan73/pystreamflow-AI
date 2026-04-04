import os
import hashlib
import streamlit as st
from dotenv import load_dotenv

# Intentar cargar desde secrets de Streamlit primero
try:
    SUPABASE_URL = st.secrets["supabase"]["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["supabase"]["SUPABASE_KEY"]
except Exception:
    # Fallback a .env si secrets no están disponibles
    load_dotenv()
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def get_supabase_client():
    from supabase import create_client, Client

    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("Faltan SUPABASE_URL o SUPABASE_KEY en .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verificar_password(password: str, password_hash: str) -> bool:
    return hash_password(password) == password_hash


def login_usuario(username: str, password: str) -> dict:
    try:
        client = get_supabase_client()
        password_hash = hash_password(password)

        response = client.table("usuarios").select("*").eq("username", username).execute()

        if not response.data:
            return {"success": False, "error": "Usuario no encontrado"}

        usuario = response.data[0]

        if usuario["password_hash"] != password_hash:
            return {"success": False, "error": "Contraseña incorrecta"}

        return {
            "success": True,
            "user_id": usuario["id"],
            "username": usuario["username"],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def registrar_usuario(username: str, password: str) -> dict:
    try:
        client = get_supabase_client()
        password_hash = hash_password(password)

        existing = client.table("usuarios").select("id").eq("username", username).execute()
        if existing.data:
            return {"success": False, "error": "El usuario ya existe"}

        response = (
            client.table("usuarios")
            .insert({"username": username, "password_hash": password_hash})
            .execute()
        )

        if response.data:
            return {
                "success": True,
                "user_id": response.data[0]["id"],
                "username": username,
            }
        return {"success": False, "error": "Error al crear usuario"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cargar_transacciones(user_id: str) -> list:
    try:
        client = get_supabase_client()
        response = client.table("transacciones").select("*").eq("user_id", user_id).execute()
        return response.data or []
    except Exception as e:
        print(f"Error cargando transacciones: {e}")
        return []


def guardar_transaccion(user_id: str, transaccion: dict) -> dict:
    try:
        client = get_supabase_client()
        transaccion["user_id"] = user_id
        response = client.table("transacciones").insert(transaccion).execute()
        return {"success": True, "data": response.data}
    except Exception as e:
        return {"success": False, "error": str(e)}


def eliminar_transaccion(user_id: str, transaccion_id: str) -> dict:
    try:
        client = get_supabase_client()
        client.table("transacciones").delete().eq("id", transaccion_id).eq(
            "user_id", user_id
        ).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cargar_presupuestos(user_id: str) -> dict:
    try:
        client = get_supabase_client()
        response = client.table("presupuestos").select("*").eq("user_id", user_id).execute()
        return {
            row["categoria"]: {"limite": row["monto"], "gastado": 0}
            for row in (response.data or [])
        }
    except:
        return {}


def guardar_presupuesto(user_id: str, categoria: str, monto: float) -> dict:
    try:
        client = get_supabase_client()
        client.table("presupuestos").upsert(
            {"user_id": user_id, "categoria": categoria, "monto": monto},
            on_conflict="user_id,categoria",
        ).execute()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def guardar_metas_ahorro(user_id: str, metas: dict) -> dict:
    """
    Guarda las metas de ahorro en Supabase.
    Las metas se almacenan como un campo JSON en una tabla de usuario o en una tabla separada.
    """
    try:
        client = get_supabase_client()
        # Opción 1: Guardar en tabla de usuarios (si existe campo metas_ahorro)
        # client.table("usuarios").update({"metas_ahorro": metas}).eq("id", user_id).execute()

        # Opción 2: Guardar en tabla separada (recomendada)
        # Primero, limpiar metas antiguas
        client.table("metas_ahorro").delete().eq("user_id", user_id).execute()

        # Insertar nuevas metas
        for meta_id, meta_data in metas.items():
            meta_data["user_id"] = user_id
            meta_data["meta_id"] = meta_id
            client.table("metas_ahorro").insert(meta_data).execute()

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def cargar_metas_ahorro(user_id: str) -> dict:
    """
    Carga las metas de ahorro desde Supabase.
    """
    try:
        client = get_supabase_client()
        response = client.table("metas_ahorro").select("*").eq("user_id", user_id).execute()

        # Convertir lista de metas a diccionario con meta_id como clave
        metas = {}
        for meta in response.data or []:
            meta_id = meta.get("meta_id")
            if meta_id:
                metas[meta_id] = meta

        return metas
    except Exception as e:
        print(f"Error cargando metas: {e}")
        return {}
