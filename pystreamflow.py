import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import re
import os
from dotenv import load_dotenv
from huggingface_hub import InferenceClient
import auth
import database

# ============================
# CONFIGURACIÓN
# ============================

MONEDAS = {
    "ARS": {"simbolo": "$", "flag": "🇦🇷", "nombre": "Pesos Argentinos"},
}

COLORES = {
    "ingreso": "#10B981",
    "gasto": "#EF4444",
    "balance_pos": "#3B82F6",
    "balance_neg": "#F59E0B",
    "primario": "#6366F1",
    "fondo": "#0f172a",
    "card": "rgba(30, 41, 59, 0.8)",
    "texto": "#f8fafc",
    "texto_sec": "#94a3b8",
}


def icon_fa(tipo):
    """Retorna emoji basado en el tipo"""
    iconos = {
        "ingreso": "🟢",
        "gasto": "🔴",
        "robot": "🤖",
        "bienvenida": "✨",
        "mensaje": "💬",
        "enviar": "📤",
        "check": "✅",
        "warning": "⚠️",
        "error": "❌",
        "ingresos_titulo": "🟢",
        "gastos_titulo": "🔴",
        "presupuesto_ok": "✅",
        "presupuesto_warn": "⚠️",
        "presupuesto_alert": "🚨",
        "online": "🟢",
        "offline": "🔴",
    }
    return iconos.get(tipo, "")


def icono_tipo_transaccion(tipo):
    """Retorna emoji para tipo de transacción (ingreso/gasto)"""
    return "🟢" if tipo == "Ingreso" else "🔴"


CATEGORIAS = {
    "Ingreso": [
        "Salario",
        "Freelance",
        "Saldo inicial",
        "Inversiones",
        "Regalos",
        "Otros",
    ],
    "Gasto": [
        "Comida",
        "Vivienda",
        "Transporte",
        "Salud",
        "Ocio",
        "Servicios",
        "Educación",
        "Otros",
    ],
}

# Placeholders dinámicos para descripción según categoría
PLACEHOLDERS_DESCRIPCION = {
    # Ingresos
    "Salario": "Ej: Sueldo mes de enero",
    "Freelance": "Ej: Diseño web proyecto X",
    "Saldo inicial": "Ej: Ahorros iniciales 2026",
    "Inversiones": "Ej: Rendimiento FCI",
    "Regalos": "Ej: Dinero de cumpleaños",
    "Otros": "Ej: Ingreso extra",
    # Gastos
    "Comida": "Ej: Supermercado, restaurantes",
    "Vivienda": "Ej: Alquiler, expensas, gas",
    "Transporte": "Ej: Uber, colectivo, nafta",
    "Salud": "Ej: Farmacia, médico, obra social",
    "Ocio": "Ej: Cine, salidas, hobbies",
    "Servicios": "Ej: Internet, luz, agua",
    "Educación": "Ej: Curso, libros, matrícula",
    "Otros": "Ej: Varios gastos",
}

# Paginación historial
ITEMS_POR_PAGINA = 20

# ============================
# FUNCIONES DE UTILIDADES
# ============================


def get_categorias(tipo, session_state):
    """Obtiene categorías (base + custom) para un tipo"""
    cats = CATEGORIAS.get(tipo, []).copy()
    custom_cats = session_state.get("categorias_custom", {}).get(tipo, [])
    for cat in custom_cats:
        if cat not in cats:
            cats.append(cat)
    return cats


def guardar_categoria_custom(tipo, categoria):
    """Guarda una categoría custom del usuario"""
    if "categorias_custom" not in st.session_state:
        st.session_state.categorias_custom = {"Ingreso": [], "Gasto": []}
    if categoria not in st.session_state.categorias_custom.get(tipo, []):
        if tipo not in st.session_state.categorias_custom:
            st.session_state.categorias_custom[tipo] = []
        st.session_state.categorias_custom[tipo].append(categoria)
        database.guardar_categoria_custom(tipo, categoria)


def generar_alertas_presupuesto():
    """Genera alertas de presupuesto excedido"""
    alertas = []
    df = get_df()
    if df.empty:
        return alertas

    mes_actual = datetime.now().strftime("%Y-%m")
    df["fecha_dt"] = pd.to_datetime(df["fecha"])
    df_mes = df[(df["fecha_dt"].dt.strftime("%Y-%m") == mes_actual) & (df["tipo"] == "Gasto")]

    for categoria, datos in st.session_state.presupuestos.items():
        gastado = df_mes[df_mes["categoria"] == categoria]["monto"].sum()
        limite = datos.get("limite", 0)
        if limite > 0:
            porcentaje = (gastado / limite) * 100
            if porcentaje >= 100:
                alertas.append(
                    {
                        "tipo": "error",
                        "categoria": categoria,
                        "mensaje": f"🚨 {categoria}: Excedido ({porcentaje:.0f}%)",
                        "gastado": gastado,
                        "limite": limite,
                    }
                )
            elif porcentaje >= 80:
                alertas.append(
                    {
                        "tipo": "warning",
                        "categoria": categoria,
                        "mensaje": f"⚠️ {categoria}: Cerca del límite ({porcentaje:.0f}%)",
                        "gastado": gastado,
                        "limite": limite,
                    }
                )
    return alertas


def generar_pdf_reporte(df, metricas, titulo="Reporte Financiero"):
    """Genera un PDF simple con el reporte"""
    from io import BytesIO

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph(titulo, styles["Title"]))
        story.append(Spacer(1, 12))

        fecha = datetime.now().strftime("%d/%m/%Y %H:%M")
        story.append(Paragraph(f"Generado: {fecha}", styles["Normal"]))
        story.append(Spacer(1, 20))

        data = [
            ["MÉTRICA", "VALOR"],
            ["Ingresos", formatear_monto(metricas["ingresos"])],
            ["Gastos", formatear_monto(metricas["gastos"])],
            ["Balance", formatear_monto(metricas["balance"])],
            ["Total Transacciones", str(metricas["count"])],
        ]

        table = Table(data)
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                    ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        story.append(table)
        story.append(Spacer(1, 20))

        story.append(Paragraph("Transacciones Recientes", styles["Heading2"]))
        story.append(Spacer(1, 10))

        tx_data = [["Fecha", "Tipo", "Categoría", "Monto"]]
        for _, row in df.head(10).iterrows():
            tx_data.append(
                [
                    row["fecha"],
                    row["tipo"],
                    row["categoria"],
                    formatear_monto(row["monto"], row["moneda"]),
                ]
            )

        tx_table = Table(tx_data)
        tx_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.darkblue),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ]
            )
        )
        story.append(tx_table)

        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue()
    except ImportError:
        return None


def render_shortcuts_help():
    """Renderiza modal de ayuda de atajos"""
    st.markdown(
        """
    <style>
    .shortcuts-modal {
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: rgba(30, 41, 59, 0.98);
        padding: 30px;
        border-radius: 16px;
        border: 1px solid rgba(99, 102, 241, 0.4);
        z-index: 9999;
        min-width: 300px;
    }
    .shortcut-item {
        display: flex;
        justify-content: space-between;
        padding: 8px 0;
        border-bottom: 1px solid rgba(255,255,255,0.1);
    }
    .shortcut-key {
        background: rgba(99, 102, 241, 0.3);
        padding: 4px 8px;
        border-radius: 4px;
        font-family: monospace;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )


# ============================
# MODELO
# ============================


@dataclass
class Transaccion:
    id: str
    tipo: str
    monto: float
    categoria: str
    descripcion: str
    fecha: str
    moneda: str

    def to_dict(self):
        return asdict(self)


# ============================
# INICIALIZACIÓN
# ============================


def init_state():
    defaults = {
        "transacciones": [],
        "moneda_activa": "ARS",
        "vista": "Dashboard",
        "filtro_fecha_inicio": (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d"),
        "filtro_fecha_fin": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "input_monto_raw": "",
        "monto_detectado": None,
        "moneda_detectada": "ARS",
        "confirmar_borrar": False,
        "presupuestos": {},
        "mes_presupuesto": datetime.now().strftime("%Y-%m"),
        "metas_ahorro": {},
        "mostrar_chat": False,
        "historial_chat": [],
        "logged_in": False,
        "user_id": None,
        "username": None,
        "modo_offline": False,
        "ultimo_guardado": None,
    }

    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    database.init_db()

    if not st.session_state.get("datos_cargados", False):
        st.session_state.transacciones = database.cargar_transacciones()
        st.session_state.presupuestos = database.cargar_presupuestos()
        st.session_state.metas_ahorro = database.cargar_metas()
        st.session_state.categorias_custom = database.cargar_categorias_custom()

        config = database.cargar_config()
        if config:
            if config.get("filtro_fecha_inicio"):
                st.session_state.filtro_fecha_inicio = config["filtro_fecha_inicio"]
            if config.get("filtro_fecha_fin"):
                st.session_state.filtro_fecha_fin = config["filtro_fecha_fin"]

        st.session_state.datos_cargados = True


# ============================
# FUNCIONES UTILITARIAS
# ============================


def generar_id():
    """Genera ID único usando timestamp completo + microsegundos + random"""
    from random import randint

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    random_part = randint(100, 999)
    return f"txn_{timestamp}_{random_part}"


def formatear_monto(valor, moneda=None):
    if moneda is None:
        moneda = st.session_state.moneda_activa
    info = MONEDAS[moneda]
    if valor == int(valor):
        return f"{info['simbolo']} {int(valor):,}"
    return f"{info['simbolo']} {valor:,.2f}"


def _parsear_numero(texto_numero):
    """Parsea un string de número manejando formatos americano y europeo"""
    texto = texto_numero.strip()

    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        partes = texto.split(",")
        if len(partes) == 2:
            parte_decimal = partes[1]
            parte_entera = partes[0]

            if len(parte_decimal) == 3 and parte_entera.replace(".", "").isdigit():
                texto = texto.replace(",", "")
            elif len(parte_decimal) <= 2:
                texto = texto.replace(",", ".")
            else:
                texto = texto.replace(",", "")
        elif texto.count(",") > 1:
            texto = texto.replace(",", "")

    try:
        return float(texto)
    except ValueError:
        return None


def detectar_moneda(texto):
    """Detecta el monto de una transacción (siempre devuelve ARS)"""
    if not texto:
        return None, None

    nums = re.findall(r"[\d.,]+", texto)
    if nums:
        numero = _parsear_numero(nums[0])
        if numero is not None:
            return numero, "ARS"

    return None, None


def get_df(moneda="ARS"):
    """Obtiene DataFrame de transacciones filtradas por moneda (por defecto ARS)"""
    df = pd.DataFrame(st.session_state.transacciones)
    if df.empty:
        return df

    if moneda:
        df = df[df["moneda"] == moneda].copy()

    if "fecha" in df.columns:
        df["fecha_dt"] = pd.to_datetime(df["fecha"])
        fecha_inicio = pd.to_datetime(st.session_state.filtro_fecha_inicio)
        fecha_fin = pd.to_datetime(st.session_state.filtro_fecha_fin)
        df = df[(df["fecha_dt"] >= fecha_inicio) & (df["fecha_dt"] <= fecha_fin)]

    return df.sort_values("fecha", ascending=False)


def cargar_datos_usuario():
    if (
        st.session_state.logged_in
        and st.session_state.user_id
        and not st.session_state.get("modo_offline", False)
    ):
        try:
            transacciones = auth.cargar_transacciones(st.session_state.user_id)
            st.session_state.transacciones = transacciones
            st.session_state.presupuestos = auth.cargar_presupuestos(st.session_state.user_id)
            if hasattr(auth, "cargar_metas_ahorro"):
                st.session_state.metas_ahorro = auth.cargar_metas_ahorro(st.session_state.user_id)

            database.sincronizar_desde_supabase(
                transacciones,
                st.session_state.presupuestos,
                st.session_state.metas_ahorro,
            )

            st.session_state.transacciones = database.cargar_transacciones()
            st.session_state.presupuestos = database.cargar_presupuestos()
            st.session_state.metas_ahorro = database.cargar_metas()
        except Exception as e:
            st.warning(f"Modo offline: {e}")
            st.session_state.modo_offline = True


def calcular_metricas(df):
    if df.empty:
        return {"ingresos": 0, "gastos": 0, "balance": 0, "count": 0}

    ing = df[df["tipo"] == "Ingreso"]["monto"].sum()
    gas = df[df["tipo"] == "Gasto"]["monto"].sum()

    return {"ingresos": ing, "gastos": gas, "balance": ing - gas, "count": len(df)}


def obtener_contexto_financiero():
    """Obtiene datos financieros actuales para dar contexto a la IA"""
    df = get_df()

    if df.empty:
        return {
            "ingresos": 0,
            "gastos": 0,
            "balance": 0,
            "top_categoria": "Sin datos",
            "total_transacciones": 0,
        }

    ingresos = df[df["tipo"] == "Ingreso"]["monto"].sum()
    gastos = df[df["tipo"] == "Gasto"]["monto"].sum()

    gastos_por_cat = df[df["tipo"] == "Gasto"].groupby("categoria")["monto"].sum()
    top_cat = gastos_por_cat.idxmax() if not gastos_por_cat.empty else "Sin gastos"

    return {
        "ingresos": ingresos,
        "gastos": gastos,
        "balance": ingresos - gastos,
        "top_categoria": top_cat,
        "total_transacciones": len(df),
    }


# ============================
# CSS (cargado desde archivo externo)
# ============================


def css():
    with open("style.css", "r") as f:
        css_content = f.read()
    st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)


# ============================
# FUNCIÓN DE IA (HuggingFace + respaldo local)
# ============================


def consultar_ia(pregunta, contexto):
    """
    Función principal que intenta usar HuggingFace y fallback a local
    """
    try:
        # Intentar cargar desde secrets de Streamlit primero
        try:
            token = st.secrets["huggingface"]["HF_TOKEN"]
        except Exception:
            # Fallback a .env si secrets no están disponibles
            load_dotenv()
            token = os.getenv("HF_TOKEN")

        if not token:
            return consultar_ia_local(pregunta, contexto)

        # Crear cliente de HuggingFace
        client = InferenceClient(token=token)

        # Construir mensajes en formato chat
        system_message = "Eres un asesor financiero experto, amigable y práctico. Respondes en español de manera clara y concisa."

        user_message = f"""
Contexto financiero del usuario:
- Ingresos: ${contexto.get("ingresos", 0):.2f}
- Gastos: ${contexto.get("gastos", 0):.2f}
- Balance: ${contexto.get("balance", 0):.2f}
- Categoría con más gastos: {contexto.get("top_categoria", "No disponible")}
- Total de transacciones: {contexto.get("total_transacciones", 0)}

Pregunta del usuario: {pregunta}

Respondé de manera útil, breve y en español.
"""

        # Usar Zephyr - modelo que SÍ funciona con Inference Providers
        response = client.chat_completion(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            model="HuggingFaceH4/zephyr-7b-beta",
            max_tokens=300,
            temperature=0.7,
        )

        return response.choices[0].message.content

    except Exception as e:
        # Si HuggingFace falla, usamos respuestas locales
        return consultar_ia_local(pregunta, contexto)


def consultar_ia_local(pregunta, contexto):
    """
    Versión de respaldo 100% local con memoria de la última conversación
    """
    pregunta_lower = pregunta.lower()

    # Detectar preguntas de seguimiento (cortas, sin palabras clave)
    palabras_clave = [
        "saldo",
        "balance",
        "gasto",
        "gastos",
        "ahorrar",
        "ahorro",
        "consejo",
        "consejos",
        "ingreso",
        "ingresos",
    ]
    es_seguimiento = len(pregunta.split()) < 4 and not any(
        k in pregunta_lower for k in palabras_clave
    )

    # Si no hay transacciones
    if contexto.get("total_transacciones", 0) == 0:
        return (
            "📝 Aún no tienes transacciones. Agrega algunas para obtener consejos personalizados."
        )

    # Obtener datos relevantes
    balance = contexto.get("balance", 0)
    ingresos = contexto.get("ingresos", 0)
    gastos = contexto.get("gastos", 0)
    top_cat = contexto.get("top_categoria", "No disponible")
    moneda = st.session_state.moneda_activa

    # Buscar el monto real de la categoría principal
    df = get_df()
    monto_top_cat = 0
    if not df.empty and top_cat != "No disponible":
        monto_top_cat = df[df["categoria"] == top_cat]["monto"].sum()

    # Guardar el último tema en session_state para seguimiento
    if "ultimo_tema" not in st.session_state:
        st.session_state.ultimo_tema = None

    # Respuestas principales
    if "saldo" in pregunta_lower or "balance" in pregunta_lower or "cuánto tengo" in pregunta_lower:
        st.session_state.ultimo_tema = "saldo"
        if balance > 0:
            return f"💰 Tu saldo es {formatear_monto(balance, moneda)} (positivo). ¡Bien!"
        else:
            return (
                f"⚠️ Tu saldo es {formatear_monto(balance, moneda)} (negativo). Revisa tus gastos."
            )

    elif "gasto" in pregunta_lower or "gastos" in pregunta_lower:
        st.session_state.ultimo_tema = "gastos"
        if "mayor" in pregunta_lower or "más" in pregunta_lower or "principal" in pregunta_lower:
            return f"📊 Tu mayor gasto es en '{top_cat}' por {formatear_monto(monto_top_cat, moneda)}. Considera si puedes reducirlo."
        else:
            return f"📊 Tus gastos totales son {formatear_monto(gastos, moneda)}. El mayor es '{top_cat}' con {formatear_monto(monto_top_cat, moneda)}."

    elif "ahorrar" in pregunta_lower or "ahorro" in pregunta_lower:
        st.session_state.ultimo_tema = "ahorro"
        if ingresos > 0:
            prop = (ingresos - gastos) / ingresos * 100
            if prop < 10:
                return f"📉 Ahorras solo el {prop:.1f}% de tus ingresos. Podrías reducir gastos en '{top_cat}' ({formatear_monto(monto_top_cat, moneda)})."
            elif prop < 20:
                return f"📈 Ahorras el {prop:.1f}%. ¡Bien! Para llegar al 20%, revisa '{top_cat}' ({formatear_monto(monto_top_cat, moneda)})."
            else:
                return f"🎉 ¡Excelente! Ahorras el {prop:.1f}%. Considera invertir."
        else:
            return "📝 Para ahorrar, primero registra tus ingresos."

    elif "ingreso" in pregunta_lower or "ingresos" in pregunta_lower:
        st.session_state.ultimo_tema = "ingresos"
        return f"📈 Tus ingresos totales son {formatear_monto(ingresos, moneda)}."

    # Detectar preguntas de seguimiento (como "de cuanto fue?")
    elif es_seguimiento:
        if st.session_state.ultimo_tema == "gastos":
            return f"Hablando de gastos, el mayor fue '{top_cat}' con {formatear_monto(monto_top_cat, moneda)}. ¿Querés saber algo más específico?"
        elif st.session_state.ultimo_tema == "saldo":
            return f"Tu saldo es {formatear_monto(balance, moneda)}. ¿Necesitas más detalles?"
        elif st.session_state.ultimo_tema == "ahorro":
            prop = (ingresos - gastos) / ingresos * 100 if ingresos > 0 else 0
            return f"Tu ahorro actual es del {prop:.1f}%. El mayor gasto es '{top_cat}' con {formatear_monto(monto_top_cat, moneda)}."
        else:
            return f"Estábamos hablando de finanzas. ¿Querés saber sobre saldo, gastos o ahorro?"

    else:
        return f"{icon_fa('robot')} Puedo ayudarte con: saldo, gastos (incluyendo el mayor), ingresos, ahorro, o consejos personalizados si agregas más transacciones."


# ============================
# CHAT DE IA (componente flotante)
# ============================


def render_chat_interface():
    """Renderiza el chat flotante con diseño moderno"""

    # CSS para el chat moderno y prolijo
    st.markdown(
        """
    <style>
    /* Estilos generales para iconos Font Awesome */
    .fas, .far, .fab {
        vertical-align: middle !important;
    }
    
    /* Contenedor del botón flotante */
    .float-ia-container {
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 9999;
    }
    
    /* Animación de pulso para el botón del asistente */
    @keyframes ia-pulse {
        0% {
            box-shadow: 0 0 0 0 rgba(99, 102, 241, 0.7);
        }
        70% {
            box-shadow: 0 0 0 15px rgba(99, 102, 241, 0);
        }
        100% {
            box-shadow: 0 0 0 0 rgba(99, 102, 241, 0);
        }
    }
    
    /* Estilo para el botón dentro del popover */
    div[data-testid="stPopover"] button {
        background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
        color: white !important;
        width: 65px !important;
        height: 65px !important;
        border-radius: 50% !important;
        font-size: 28px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        box-shadow: 0 4px 20px rgba(99, 102, 241, 0.5) !important;
        border: 3px solid rgba(255, 255, 255, 0.2) !important;
        transition: all 0.3s ease !important;
        animation: ia-pulse 2s infinite !important;
    }
    
    /* Icono dentro del botón del popover */
    div[data-testid="stPopover"] button i {
        font-size: 28px !important;
        margin: 0 !important;
        line-height: 1 !important;
    }
    
    div[data-testid="stPopover"] button:hover {
        transform: scale(1.15) !important;
        box-shadow: 0 8px 30px rgba(99, 102, 241, 0.7) !important;
        animation: none !important;
    }
    
    /* Estilo del popover - más prolijo */
    div[data-testid="stPopover"] > div {
        background: rgba(15, 23, 42, 0.98) !important;
        backdrop-filter: blur(20px) !important;
        border: 1px solid rgba(99, 102, 241, 0.4) !important;
        border-radius: 24px !important;
        box-shadow: 0 25px 80px rgba(0, 0, 0, 0.6), 0 0 40px rgba(99, 102, 241, 0.1) !important;
        padding: 0 !important;
        min-width: 380px !important;
    }
    
    /* Header del chat */
    .chat-header {
        background: linear-gradient(135deg, #6366F1 0%, #8B5CF6 50%, #A78BFA 100%) !important;
        color: white !important;
        padding: 18px 24px !important;
        border-radius: 24px 24px 0 0 !important;
        font-weight: 600 !important;
        font-size: 1.15rem !important;
        text-align: center !important;
        box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4) !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 10px !important;
    }
    
    /* Contenedor del historial */
    .chat-container {
        max-height: 380px !important;
        overflow-y: auto !important;
        padding: 20px !important;
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.3) 0%, rgba(30, 41, 59, 0.5) 100%) !important;
    }
    
    /* Burbujas de chat - diseño técnico */
    .chat-bubble-user {
        background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
        color: white !important;
        padding: 14px 18px !important;
        border-radius: 20px 20px 6px 20px !important;
        margin: 14px 0 !important;
        max-width: 85% !important;
        margin-left: auto !important;
        font-size: 0.92rem !important;
        line-height: 1.5 !important;
        box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3) !important;
        border: 1px solid rgba(255, 255, 255, 0.15) !important;
    }
    
    .chat-bubble-assistant {
        background: linear-gradient(135deg, #1e293b, #334155) !important;
        color: #e2e8f0 !important;
        padding: 14px 18px !important;
        border-radius: 20px 20px 20px 6px !important;
        margin: 14px 0 !important;
        max-width: 85% !important;
        font-size: 0.92rem !important;
        line-height: 1.5 !important;
        border: 1px solid rgba(99, 102, 241, 0.2) !important;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2) !important;
    }
    
    /* Contenedor de input */
    .chat-input-container {
        background: linear-gradient(180deg, rgba(30, 41, 59, 0.9) 0%, rgba(30, 41, 59, 1) 100%) !important;
        padding: 16px 20px !important;
        border-top: 1px solid rgba(99, 102, 241, 0.3) !important;
        border-radius: 0 0 24px 24px !important;
        display: flex !important;
        gap: 12px !important;
        align-items: center !important;
    }
    
    /* Input de texto del chat */
    .chat-input-container .stTextInput > div > div > input {
        background: rgba(15, 23, 42, 0.9) !important;
        border: 1px solid rgba(99, 102, 241, 0.4) !important;
        border-radius: 14px !important;
        color: #f8fafc !important;
        padding: 12px 16px !important;
    }
    
    .chat-input-container .stTextInput > div > div > input:focus {
        border-color: #6366F1 !important;
        box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.3) !important;
    }
    
    /* Botón de enviar del chat */
    .chat-input-container .stButton button {
        background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
        color: white !important;
        border: none !important;
        border-radius: 14px !important;
        padding: 12px 20px !important;
        font-weight: 500 !important;
        transition: all 0.2s ease !important;
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3) !important;
    }
    
    .chat-input-container .stButton button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 18px rgba(99, 102, 241, 0.5) !important;
    }
    
    /* Scrollbar personalizado para el chat */
    .chat-container::-webkit-scrollbar {
        width: 8px !important;
    }
    
    .chat-container::-webkit-scrollbar-track {
        background: rgba(30, 41, 59, 0.3) !important;
        border-radius: 4px !important;
    }
    
    .chat-container::-webkit-scrollbar-thumb {
        background: linear-gradient(180deg, #6366F1, #8B5CF6) !important;
        border-radius: 4px !important;
    }
    
    .chat-container::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(180deg, #8B5CF6, #A78BFA) !important;
    }
    
    /* Animación de escritura */
    @keyframes typing {
        0%, 100% { opacity: 0.3; transform: scale(0.8); }
        50% { opacity: 1; transform: scale(1); }
    }
    
    .typing-indicator {
        display: inline-flex;
        gap: 5px;
        padding: 12px 16px;
        background: linear-gradient(135deg, #1e293b, #334155);
        border-radius: 18px;
        margin: 12px 0;
        border: 1px solid rgba(99, 102, 241, 0.2);
    }
    
    .typing-indicator span {
        width: 8px;
        height: 8px;
        background: linear-gradient(135deg, #6366F1, #8B5CF6);
        border-radius: 50%;
        animation: typing 1.4s infinite ease-in-out;
    }
    
    .typing-indicator span:nth-child(2) {
        animation-delay: 0.2s;
    }
    
    .typing-indicator span:nth-child(3) {
        animation-delay: 0.4s;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # Contenedor flotante para el popover
    st.markdown('<div class="float-ia-container">', unsafe_allow_html=True)

    # Popover con el botón - usando icono de material
    with st.popover("🤖", use_container_width=False):
        # Header del chat
        st.markdown(
            f'<div class="chat-header">{icon_fa("robot")} Asistente Financiero IA</div>',
            unsafe_allow_html=True,
        )

        # Contenedor del historial de chat
        st.markdown('<div class="chat-container">', unsafe_allow_html=True)

        # Mostrar historial con diseño de burbujas
        if not st.session_state.get("historial_chat"):
            st.markdown(
                '<div class="chat-bubble-assistant">'
                f"{icon_fa('bienvenida')} Soy tu asistente financiero IA. "
                "Puedo ayudarte a analizar tus gastos, sugerir presupuestos, "
                "y responder preguntas sobre tus finanzas. ¿En qué puedo ayudarte hoy?"
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            for msg in st.session_state.historial_chat:
                if msg["role"] == "user":
                    st.markdown(
                        f'<div class="chat-bubble-user">{icon_fa("mensaje")} {msg["content"]}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div class="chat-bubble-assistant">{icon_fa("robot")} {msg["content"]}</div>',
                        unsafe_allow_html=True,
                    )

        st.markdown("</div>", unsafe_allow_html=True)

        # Input para pregunta con mejor diseño
        st.markdown('<div class="chat-input-container">', unsafe_allow_html=True)

        col1, col2 = st.columns([3, 1])
        with col1:
            pregunta = st.text_input(
                "Escribe tu pregunta...",
                placeholder="¿Cómo puedo ahorrar más este mes?",
                key="ia_input_popover",
                label_visibility="collapsed",
            )

        with col2:
            if st.button(
                "Enviar",
                key="ia_send_popover",
                use_container_width=True,
                icon="🚀",
            ):
                if pregunta:
                    # Agregar pregunta
                    if "historial_chat" not in st.session_state:
                        st.session_state.historial_chat = []
                    st.session_state.historial_chat.append({"role": "user", "content": pregunta})

                    # Consultar IA
                    with st.spinner("Pensando..."):
                        contexto = obtener_contexto_financiero()
                        respuesta = consultar_ia(pregunta, contexto)

                    # Agregar respuesta
                    st.session_state.historial_chat.append(
                        {"role": "assistant", "content": respuesta}
                    )

                    # Forzar actualización
                    st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


# ============================
# VISTAS
# ============================


def obtener_widgets_resumen(df, met):
    """Obtiene métricas adicionales para widgets del dashboard"""
    if df.empty:
        return {
            "dia_mayor_gasto": "Sin datos",
            "cat_mayor_ahorro": "Sin datos",
            "progreso_mes": 0,
            "promedio_diario": 0,
            "gasto_promedio": 0,
        }

    dia_mayor_gasto = "Sin gastos"
    cat_mayor_ingreso = "Sin ingresos"

    gastos = df[df["tipo"] == "Gasto"]
    if not gastos.empty:
        gasto_por_dia = gastos.groupby("fecha")["monto"].sum()
        if not gasto_por_dia.empty:
            dia_max = gasto_por_dia.idxmax()
            dia_mayor_gasto = f"{dia_max} ({formatear_monto(gasto_por_dia.max())})"

    ingresos = df[df["tipo"] == "Ingreso"]
    if not ingresos.empty:
        ing_por_cat = ingresos.groupby("categoria")["monto"].sum()
        if not ing_por_cat.empty:
            cat_mayor_ingreso = ing_por_cat.idxmax()

    fecha_inicio = pd.to_datetime(st.session_state.filtro_fecha_inicio)
    fecha_fin = pd.to_datetime(st.session_state.filtro_fecha_fin)
    dias_transcurridos = (fecha_fin - fecha_inicio).days + 1

    promedio_diario = met["gastos"] / dias_transcurridos if dias_transcurridos > 0 else 0

    df["fecha_dt"] = pd.to_datetime(df["fecha"])
    mes_actual = datetime.now().strftime("%Y-%m")
    df_mes = df[df["fecha_dt"].dt.strftime("%Y-%m") == mes_actual]

    if not df_mes.empty and met["gastos"] > 0:
        gastos_mes = df_mes[df_mes["tipo"] == "Gasto"]["monto"].sum()
        presupuesto_promedio = st.session_state.presupuestos
        if presupuesto_promedio:
            promedio_presupuesto = sum(p["limite"] for p in presupuesto_promedio.values()) / len(
                presupuesto_promedio
            )
            progreso_mes = (
                (gastos_mes / promedio_presupuesto * 100) if promedio_presupuesto > 0 else 0
            )
        else:
            progreso_mes = 50
    else:
        progreso_mes = 0
        gastos_mes = 0

    gasto_promedio = met["gastos"] / len(gastos) if not gastos.empty else 0

    return {
        "dia_mayor_gasto": dia_mayor_gasto,
        "cat_mayor_ingreso": cat_mayor_ingreso,
        "progreso_mes": min(progreso_mes, 100),
        "promedio_diario": promedio_diario,
        "gasto_promedio": gasto_promedio,
    }


def vista_dashboard():
    st.markdown("# 📊 Dashboard")
    st.markdown("---")

    # Notificación de transacción guardada
    if st.session_state.get("ultimo_guardado"):
        info = st.session_state.ultimo_guardado
        color = COLORES["ingreso"] if info["tipo"] == "Ingreso" else COLORES["gasto"]
        icono = "🟢" if info["tipo"] == "Ingreso" else "🔴"
        st.markdown(
            f"""
        <div style="
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.15), rgba(16, 185, 129, 0.05));
            border: 1px solid rgba(16, 185, 129, 0.4);
            border-radius: 12px;
            padding: 16px 20px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 12px;
        ">
            <span style="font-size: 1.5rem;">{icono}</span>
            <div>
                <div style="color: {COLORES["texto"]}; font-weight: 600; font-size: 1rem;">
                    ¡Transacción guardada exitosamente!
                </div>
                <div style="color: {COLORES["texto_sec"]}; font-size: 0.875rem;">
                    {info["tipo"]}: {formatear_monto(info["monto"], info["moneda"])}
                </div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )
        del st.session_state["ultimo_guardado"]

    # Tutorial Onboarding para nuevos usuarios
    if not st.session_state.get("onboarding_completado", False):
        with st.container():
            st.markdown("### 📚 Guía Rápida - Primeros Pasos")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.markdown(
                    """
                <div class="onboarding-step">
                    <h3>1️⃣ Registra</h3>
                    <p>Ve a <span class="onboarding-highlight">Nueva</span> y agrega tus ingresos y gastos. 
                    Usa formatos como <code>15000</code> o <code>1.500,50</code>.</p>
                </div>
                """,
                    unsafe_allow_html=True,
                )
            with col2:
                st.markdown(
                    """
                <div class="onboarding-step">
                    <h3>2️⃣ Organiza</h3>
                    <p>Asigna categorías a cada transacción para ver dónde va tu dinero.
                    Puedes crear <span class="onboarding-highlight">categorías custom</span>.</p>
                </div>
                """,
                    unsafe_allow_html=True,
                )
            with col3:
                st.markdown(
                    """
                <div class="onboarding-step">
                    <h3>3️⃣ Controla</h3>
                    <p>Usa <span class="onboarding-highlight">Presupuestos</span> para limitar gastos
                    y <span class="onboarding-highlight">Metas</span> para ahorrar.</p>
                </div>
                """,
                    unsafe_allow_html=True,
                )

            st.markdown(
                """
            <div class="onboarding-step">
                <h3>⌨️ Atajos de teclado</h3>
                <p>
                    <span class="onboarding-highlight">Ctrl + N</span> Nueva transacción &nbsp;|&nbsp;
                    <span class="onboarding-highlight">Ctrl + H</span> Historial &nbsp;|&nbsp;
                    <span class="onboarding-highlight">Ctrl + D</span> Dashboard
                </p>
            </div>
            """,
                unsafe_allow_html=True,
            )

            no_mostrar = st.checkbox(
                "☑️ No mostrar más esta guía",
                value=False,
                key="onboarding_checkbox",
            )
            if no_mostrar:
                st.session_state.onboarding_completado = True
                st.rerun()

    total_global = len(st.session_state.transacciones)

    if total_global == 0:
        st.markdown(
            f"<div style='background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.3); border-radius: 12px; padding: 16px; margin-bottom: 16px;'>{icon_fa('bienvenida')} ¡Bienvenido! No tienes transacciones.</div>",
            unsafe_allow_html=True,
        )

        if st.button(
            "Agregar primera transacción",
            type="primary",
            use_container_width=True,
            icon="➕",
        ):
            st.session_state.vista = "Nueva"
            st.rerun()
        return

    moneda = st.session_state.moneda_activa
    info = MONEDAS[moneda]
    st.markdown(f"### {info['flag']} {info['nombre']}")

    df = get_df(moneda)
    met = calcular_metricas(df)

    c1, c2, c3 = st.columns(3)

    with c1:
        st.metric(
            "💰 Ingresos",
            formatear_monto(met["ingresos"]),
            f"{met['count']} trans.",
            help="Suma total de ingresos en el período seleccionado",
        )

    with c2:
        st.metric(
            "💸 Gastos",
            formatear_monto(met["gastos"]),
            help="Suma total de gastos en el período seleccionado",
        )

    with c3:
        color = "normal" if met["balance"] >= 0 else "inverse"
        st.metric(
            "⚖️ Balance",
            formatear_monto(abs(met["balance"])),
            "Positivo" if met["balance"] >= 0 else "Negativo",
            delta_color=color,
            help="Diferencia entre ingresos y gastos (Ingresos - Gastos)",
        )

    # Mostrar alertas de presupuesto
    alertas = generar_alertas_presupuesto()
    if alertas:
        st.markdown("### 🔔 Alertas de Presupuesto")
        for alerta in alertas:
            if alerta["tipo"] == "error":
                st.error(alerta["mensaje"])
            else:
                st.warning(alerta["mensaje"])

    st.markdown("---")

    g1, g2 = st.columns(2)

    with g1:
        st.markdown("#### 🥧 Gastos por categoría")
        if not df.empty and met["gastos"] > 0:
            gastos = df[df["tipo"] == "Gasto"].groupby("categoria")["monto"].sum().reset_index()
            fig = px.pie(
                gastos,
                values="monto",
                names="categoria",
                hole=0.5,
                color_discrete_sequence=px.colors.sequential.Plasma_r,
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORES["texto"], family="Inter"),
                legend=dict(
                    font=dict(color=COLORES["texto"]),
                    orientation="h",
                    yanchor="bottom",
                    y=-0.1,
                ),
                margin=dict(l=20, r=20, t=30, b=60),
                hoverlabel=dict(bgcolor=COLORES["card"], font_size=12),
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin gastos en este período")

    with g2:
        st.markdown("#### 📈 Evolución")
        if not df.empty:
            df_sorted = df.sort_values("fecha")
            df_sorted["signo"] = df_sorted.apply(
                lambda x: x["monto"] if x["tipo"] == "Ingreso" else -x["monto"], axis=1
            )
            df_sorted["acum"] = df_sorted["signo"].cumsum()
            fig = px.area(
                df_sorted,
                x="fecha",
                y="acum",
                color_discrete_sequence=[COLORES["primario"]],
            )
            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORES["texto"], family="Inter"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.1)", title=""),
                yaxis=dict(gridcolor="rgba(255,255,255,0.1)", title=""),
                hoverlabel=dict(bgcolor=COLORES["card"], font_size=12),
                margin=dict(l=40, r=20, t=30, b=40),
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Sin datos en este período")

    st.markdown("---")
    st.markdown("### 📝 Últimas transacciones")

    if not df.empty:
        for _, row in df.head(5).iterrows():
            icono = icono_tipo_transaccion(row["tipo"])
            color = COLORES["ingreso"] if row["tipo"] == "Ingreso" else COLORES["gasto"]
            signo = "+" if row["tipo"] == "Ingreso" else "-"

            st.markdown(
                f"""
            <div class="transaction-card" style="border-left: 4px solid {color};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-size: 1rem;">{icono}</span>
                        <span style="font-weight: 600; color: {COLORES["texto"]}; margin-left: 8px;">
                            {row["categoria"]}
                        </span>
                        <span style="color: {COLORES["texto_sec"]}; font-size: 0.875rem; margin-left: 12px;">
                            {row["fecha"]} • {MONEDAS[row["moneda"]]["flag"]} {MONEDAS[row["moneda"]]["nombre"]}
                        </span>
                    </div>
                    <div style="font-weight: 700; color: {color}; font-size: 1.1rem;">
                        {signo}{formatear_monto(row["monto"], row["moneda"])}
                    </div>
                </div>
                {row["descripcion"] and f'<div style="color: {COLORES["texto_sec"]}; font-size: 0.875rem; margin-top: 8px; margin-left: 32px;">{row["descripcion"]}</div>' or ""}
            </div>
            """,
                unsafe_allow_html=True,
            )
    else:
        st.info("Sin transacciones en este período/filtro")


def vista_nueva():
    st.markdown("# ➕ Nueva Transacción")
    st.markdown("---")
    st.markdown("### 1. Selecciona el tipo")

    if "nuevo_tipo" not in st.session_state:
        st.session_state.nuevo_tipo = "Ingreso 💰"

    tipo_opciones = ["Ingreso 💰", "Gasto 💸"]
    tipo = st.radio(
        "Tipo de movimiento",
        options=tipo_opciones,
        index=tipo_opciones.index(st.session_state.nuevo_tipo),
        horizontal=True,
        key="tipo_selector",
    )
    st.session_state.nuevo_tipo = tipo
    tipo_clean = "Ingreso" if "Ingreso" in tipo else "Gasto"

    st.markdown("---")

    st.markdown("### 2. Ingresa el monto")

    st.info(
        "💡 **Formatos aceptados:**\n\n"
        "• `15000` - Número simple\n"
        "• `1.500,50` - Formato europeo con coma\n"
        "• `1500.50` - Formato decimal"
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        input_monto = st.text_input(
            "Monto *",
            value=st.session_state.get("input_monto_raw", ""),
            placeholder="Ej: 15000, 1.500,50",
            key="input_monto_key",
        )

    monto_valor = None
    moneda_detectada = st.session_state.moneda_activa

    if input_monto:
        monto_val, mon_val = detectar_moneda(input_monto)
        if monto_val is not None:
            monto_valor = monto_val
            moneda_detectada = mon_val if mon_val else st.session_state.get("moneda_activa", "ARS")
            # Asegurar que moneda_detectada no sea None
            if moneda_detectada is None:
                moneda_detectada = "ARS"
            st.session_state.monto_detectado = monto_valor
            st.session_state.moneda_detectada = moneda_detectada
            st.session_state.input_monto_raw = input_monto
            with col2:
                st.success(
                    f"✅ {MONEDAS[moneda_detectada]['flag']} {formatear_monto(monto_valor, moneda_detectada)}"
                )
            st.caption(
                f"💡 Quedará registrado como: **{formatear_monto(monto_valor, moneda_detectada)}**"
            )
        else:
            with col2:
                st.error("❌ Monto no válido")
    else:
        monto_valor = st.session_state.get("monto_detectado", None)
        moneda_detectada = st.session_state.get(
            "moneda_detectada", st.session_state.get("moneda_activa", "ARS")
        )
        # Asegurar que moneda_detectada no sea None
        if moneda_detectada is None:
            moneda_detectada = "ARS"

        # Mostrar ejemplo formateado cuando no hay entrada
        if monto_valor is None:
            with col2:
                st.info(
                    f"ℹ️ Formato: {MONEDAS[moneda_detectada]['flag']} {formatear_monto(15000, moneda_detectada)}"
                )

    st.markdown("---")

    st.markdown("### 3. Completa los detalles")

    with st.form(key="form_nueva"):
        col1, col2 = st.columns(2)
        with col1:
            if tipo_clean == "Ingreso":
                cat_options = CATEGORIAS["Ingreso"]
                default_cat = "Salario"
            else:
                cat_options = CATEGORIAS["Gasto"]
                default_cat = "Comida"

            default_index = cat_options.index(default_cat) if default_cat in cat_options else 0
            categoria = st.selectbox(
                "Categoría *",
                cat_options,
                index=default_index,
                key="categoria_selector",
            )

        with col2:
            placeholder_dinamico = PLACEHOLDERS_DESCRIPCION.get(categoria, "Ej: Descripción...")
            descripcion = st.text_input(
                "Descripción", placeholder=placeholder_dinamico, key="descripcion_input"
            )
            fecha = st.date_input("Fecha", datetime.now())

        if moneda_detectada is None:
            moneda_detectada = st.session_state.get("moneda_activa", "ARS")
        # Asegurar que moneda_detectada no sea None
        if moneda_detectada is None:
            moneda_detectada = "ARS"

        st.markdown(
            f"""
        <div style="background: rgba(99, 102, 241, 0.1); padding: 8px 12px; border-radius: 8px; margin: 8px 0;">
            <span style="color: {COLORES["texto_sec"]};">💰 Moneda detectada:</span>
            <span style="color: {COLORES["texto"]}; font-weight: 600; margin-left: 8px;">
                {MONEDAS[moneda_detectada]["flag"]} {MONEDAS[moneda_detectada]["nombre"]} ({MONEDAS[moneda_detectada]["simbolo"]})
            </span>
        </div>
        """,
            unsafe_allow_html=True,
        )

        submitted = st.form_submit_button(
            "💾 Guardar Transacción", use_container_width=True, type="primary"
        )

    if submitted:
        if monto_valor is None or monto_valor <= 0:
            st.error("⚠️ Ingresa un monto válido mayor a 0")
            return

        if not categoria:
            st.error("⚠️ Selecciona una categoría")
            return

        tx = Transaccion(
            id=generar_id(),
            tipo=tipo_clean,
            monto=monto_valor,
            categoria=categoria,
            descripcion=descripcion,
            fecha=fecha.strftime("%Y-%m-%d"),
            moneda=moneda_detectada,
        )
        txn_dict = tx.to_dict()
        st.session_state.transacciones.append(txn_dict)

        database.guardar_transaccion(txn_dict)

        if (
            st.session_state.logged_in
            and st.session_state.user_id
            and not st.session_state.get("modo_offline", False)
        ):
            try:
                auth.guardar_transaccion(st.session_state.user_id, txn_dict)
            except Exception:
                st.session_state.modo_offline = True

        st.session_state.input_monto_raw = ""
        st.session_state.monto_detectado = None
        st.session_state.moneda_detectada = None
        st.session_state.ultimo_guardado = {
            "tipo": tipo_clean,
            "monto": monto_valor,
            "moneda": moneda_detectada,
        }

        st.success(f"✅ {tipo_clean} guardado: {formatear_monto(monto_valor, moneda_detectada)}")
        st.balloons()
        st.rerun()


def vista_historial():
    st.markdown("# 📋 Historial de Transacciones")
    st.markdown("---")

    total_global = len(st.session_state.transacciones)
    st.caption(f"Total: **{total_global}** transacciones")

    if total_global > 0:
        st.markdown("---")

        confirmar = st.checkbox(
            "🔒 Confirmar eliminar TODAS permanentemente",
            value=st.session_state.confirmar_borrar,
            key="check_borrar",
        )

        st.session_state.confirmar_borrar = confirmar

        if confirmar:
            st.markdown(
                """
            <style>
            .btn-delete-all {
                animation: pulse-vibrate 0.5s ease-in-out infinite;
                transform: scale(1.05);
            }
            @keyframes pulse-vibrate {
                0%, 100% { transform: scale(1.05) translateX(0); }
                25% { transform: scale(1.05) translateX(-3px); }
                75% { transform: scale(1.05) translateX(3px); }
            }
            </style>
            """,
                unsafe_allow_html=True,
            )
            st.error("¡Se borrará TODO!")

            if st.button(
                "ELIMINAR TODAS",
                type="primary",
                use_container_width=True,
                help="¡Esta acción es irreversible!",
                icon="🔥",
            ):
                cantidad = len(st.session_state.transacciones)
                st.session_state.transacciones = []
                database.eliminar_todas_transacciones()
                st.session_state.input_monto_raw = ""
                st.session_state.monto_detectado = None
                st.session_state.confirmar_borrar = False

                if (
                    st.session_state.logged_in
                    and st.session_state.user_id
                    and not st.session_state.get("modo_offline", False)
                ):
                    try:
                        client = auth.get_supabase_client()
                        client.table("transacciones").delete().eq(
                            "user_id", st.session_state.user_id
                        ).execute()
                    except Exception:
                        st.session_state.modo_offline = True

                st.success(f"🗑️ ¡Eliminadas {cantidad}!")
                st.rerun()
        else:
            st.button(
                "🔥 ELIMINAR TODAS (confirma arriba)",
                type="primary",
                use_container_width=True,
                disabled=True,
            )

        st.markdown("---")

    if total_global == 0:
        st.markdown(
            f"""
        <div class="empty-state">
            <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
                <circle cx="100" cy="100" r="80" fill="rgba(99, 102, 241, 0.1)" />
                <path d="M60 80 L100 120 L140 80" stroke="{COLORES["primario"]}" stroke-width="4" fill="none" stroke-linecap="round"/>
                <circle cx="100" cy="100" r="40" fill="none" stroke="{COLORES["primario"]}" stroke-width="2" stroke-dasharray="5,5"/>
                <text x="100" y="145" text-anchor="middle" fill="{COLORES["texto_sec"]}" font-size="12">Sin datos</text>
            </svg>
            <h3>No hay transacciones</h3>
            <p>Comienza a registrar tus movimientos financieros</p>
        </div>
        """,
            unsafe_allow_html=True,
        )

        if st.button(
            "➕ Agregar primera transacción",
            type="primary",
            use_container_width=True,
            key="empty_add_btn",
        ):
            st.session_state.vista = "Nueva"
            st.rerun()
        return

    with st.expander("🔍 Filtros"):
        c1, c2 = st.columns(2)
        with c1:
            tipos = st.multiselect("Tipo", ["Ingreso", "Gasto"], default=["Ingreso", "Gasto"])
        with c2:
            todas_cats = list(set([t["categoria"] for t in st.session_state.transacciones]))
            cats = st.multiselect("Categorías", todas_cats)

        fecha_desde = st.date_input("Desde", pd.to_datetime(st.session_state.filtro_fecha_inicio))
        fecha_hasta = st.date_input("Hasta", pd.to_datetime(st.session_state.filtro_fecha_fin))

        nueva_fecha_inicio = fecha_desde.strftime("%Y-%m-%d")
        nueva_fecha_fin = fecha_hasta.strftime("%Y-%m-%d")

        if (
            nueva_fecha_inicio != st.session_state.filtro_fecha_inicio
            or nueva_fecha_fin != st.session_state.filtro_fecha_fin
        ):
            st.session_state.filtro_fecha_inicio = nueva_fecha_inicio
            st.session_state.filtro_fecha_fin = nueva_fecha_fin
            st.rerun()

    df = get_df()

    if tipos:
        df = df[df["tipo"].isin(tipos)]
    if cats:
        df = df[df["categoria"].isin(cats)]

    if df.empty:
        st.info("No hay transacciones con estos filtros.")
        return

    st.markdown(f"**Mostrando {len(df)} transacciones**")

    # Paginación
    total_items = len(df)
    total_paginas = max(1, (total_items + ITEMS_POR_PAGINA - 1) // ITEMS_POR_PAGINA)

    if "pagina_actual" not in st.session_state:
        st.session_state.pagina_actual = 1

    col_prev, col_info, col_next = st.columns([1, 2, 1])
    with col_prev:
        if st.button("⬅️ Anterior", disabled=st.session_state.pagina_actual <= 1, key="btn_prev"):
            st.session_state.pagina_actual -= 1
            st.rerun()

    with col_info:
        st.markdown(f"**Página {st.session_state.pagina_actual} de {total_paginas}**")

    with col_next:
        if st.button(
            "Siguiente ➡️", disabled=st.session_state.pagina_actual >= total_paginas, key="btn_next"
        ):
            st.session_state.pagina_actual += 1
            st.rerun()

    # Selector rápido de página
    paginas_disponibles = list(range(1, total_paginas + 1))
    if len(paginas_disponibles) > 5:
        paginas_disponibles = [1, 2, "...", total_paginas - 1, total_paginas]

    col_j1, col_j2, col_j3, col_j4, col_j5 = st.columns(5)
    cols = [col_j1, col_j2, col_j3, col_j4, col_j5]
    for i, pagina in enumerate(paginas_disponibles[:5]):
        with cols[i]:
            if st.button(str(pagina), key=f"page_{pagina}", use_container_width=True):
                st.session_state.pagina_actual = (
                    pagina if pagina != "..." else st.session_state.pagina_actual
                )
                st.rerun()

    st.markdown("### 📜 Listado")

    # Calcular índices de paginación
    inicio = (st.session_state.pagina_actual - 1) * ITEMS_POR_PAGINA
    fin = inicio + ITEMS_POR_PAGINA
    df_pagina = df.iloc[inicio:fin]

    for _, row in df_pagina.iterrows():
        icono = icono_tipo_transaccion(row["tipo"])
        color = COLORES["ingreso"] if row["tipo"] == "Ingreso" else COLORES["gasto"]
        mon_info = MONEDAS[row["moneda"]]
        monto_str = formatear_monto(row["monto"], row["moneda"])

        expander_label = f"{icono} {row['categoria']} | {monto_str} | {row['fecha']}"

        with st.expander(expander_label, expanded=False):
            # Formulario de edición inline
            with st.form(key=f"edit_{row['id']}"):
                col1, col2 = st.columns(2)
                with col1:
                    nuevo_tipo = st.selectbox(
                        "Tipo",
                        ["Ingreso", "Gasto"],
                        index=0 if row["tipo"] == "Ingreso" else 1,
                        key=f"tipo_edit_{row['id']}",
                    )
                    cats_disponibles = CATEGORIAS[nuevo_tipo]
                    cat_index = (
                        cats_disponibles.index(row["categoria"])
                        if row["categoria"] in cats_disponibles
                        else 0
                    )
                    nueva_categoria = st.selectbox(
                        "Categoría",
                        cats_disponibles,
                        index=cat_index,
                        key=f"cat_edit_{row['id']}",
                    )
                with col2:
                    nuevo_monto = st.number_input(
                        "Monto",
                        min_value=0.0,
                        value=row["monto"],
                        step=100.0,
                        key=f"monto_edit_{row['id']}",
                    )
                    nueva_fecha = st.date_input(
                        "Fecha",
                        value=pd.to_datetime(row["fecha"]),
                        key=f"fecha_edit_{row['id']}",
                    )

                nueva_descripcion = st.text_input(
                    "Descripción",
                    value=row["descripcion"],
                    key=f"desc_edit_{row['id']}",
                )

                col_guardar, col_eliminar, _ = st.columns([1, 1, 5])
                with col_guardar:
                    if st.form_submit_button("💾 Guardar", use_container_width=True):
                        for i, t in enumerate(st.session_state.transacciones):
                            if t["id"] == row["id"]:
                                st.session_state.transacciones[i] = {
                                    "id": row["id"],
                                    "tipo": nuevo_tipo,
                                    "monto": nuevo_monto,
                                    "categoria": nueva_categoria,
                                    "descripcion": nueva_descripcion,
                                    "fecha": nueva_fecha.strftime("%Y-%m-%d"),
                                    "moneda": row["moneda"],
                                }
                                database.guardar_transaccion(st.session_state.transacciones[i])
                                st.success("✅ Transacción actualizada")
                                st.rerun()

                with col_eliminar:
                    if st.form_submit_button(
                        "🗑️ Eliminar", use_container_width=True, type="secondary"
                    ):
                        st.session_state.transacciones = [
                            t for t in st.session_state.transacciones if t["id"] != row["id"]
                        ]
                        database.eliminar_transaccion(row["id"])

                        if (
                            st.session_state.logged_in
                            and st.session_state.user_id
                            and not st.session_state.get("modo_offline", False)
                        ):
                            try:
                                auth.eliminar_transaccion(st.session_state.user_id, row["id"])
                            except Exception:
                                st.session_state.modo_offline = True

                        st.success("✅ Transacción eliminada")
                        st.rerun()

        # Mantener el botón de eliminar rápido en la vista principal
        col_main, col_del = st.columns([6, 1])
        with col_main:
            st.markdown(
                f"""
            <div class="transaction-card" style="border-left: 4px solid {color};">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-size: 1rem;">{icono}</span>
                        <span style="font-weight: 600; color: {COLORES["texto"]}; margin-left: 8px;">
                            {row["categoria"]}
                        </span>
                        <span style="color: {COLORES["texto_sec"]}; font-size: 0.875rem; margin-left: 12px;">
                            {row["fecha"]} • {mon_info["flag"]} {mon_info["nombre"]}
                        </span>
                    </div>
                    <div style="font-weight: 700; color: {color}; font-size: 1.1rem;">
                        {row["tipo"] == "Ingreso" and "+" or "-"}{formatear_monto(row["monto"], row["moneda"])}
                    </div>
                </div>
                {row["descripcion"] and f'<div style="color: {COLORES["texto_sec"]}; font-size: 0.875rem; margin-top: 8px; margin-left: 32px;">{row["descripcion"]}</div>' or ""}
            </div>
            """,
                unsafe_allow_html=True,
            )

        with col_del:
            if st.button(
                "",
                key=f"del_{row['id']}",
                help="Eliminar esta transacción",
                icon="🗑️",
            ):
                st.session_state.transacciones = [
                    t for t in st.session_state.transacciones if t["id"] != row["id"]
                ]
                database.eliminar_transaccion(row["id"])

                if (
                    st.session_state.logged_in
                    and st.session_state.user_id
                    and not st.session_state.get("modo_offline", False)
                ):
                    try:
                        auth.eliminar_transaccion(st.session_state.user_id, row["id"])
                    except Exception:
                        st.session_state.modo_offline = True

                st.markdown(
                    f"""
                <div class="toast-eliminado" id="toast_{row["id"]}">
                    ✅ Eliminada: {row["categoria"]} {formatear_monto(row["monto"], row["moneda"])}
                </div>
                <script>
                    setTimeout(function() {{
                        var toast = document.getElementById('toast_{row["id"]}');
                        if (toast) toast.remove();
                    }}, 2000);
                </script>
                """,
                    unsafe_allow_html=True,
                )
                st.rerun()

    st.markdown("---")
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 Descargar CSV",
        csv,
        f"finanzas_{datetime.now().strftime('%Y%m%d')}.csv",
        "text/csv",
        use_container_width=True,
    )


def vista_graficos():
    st.markdown("# 📈 Gráficos")
    st.markdown("---")

    moneda = st.session_state.moneda_activa
    df = get_df(moneda)

    if df.empty:
        st.info(
            f"Sin datos para {MONEDAS[moneda]['flag']} {MONEDAS[moneda]['nombre']}. Agrega transacciones primero."
        )
        return

    st.caption(f"Mostrando datos en {MONEDAS[moneda]['flag']} {MONEDAS[moneda]['nombre']}")

    # Botón exportar PDF
    col_pdf, col_space = st.columns([1, 3])
    with col_pdf:
        met = calcular_metricas(df)
        pdf_data = generar_pdf_reporte(df, met)
        if pdf_data:
            st.download_button(
                "📄 Exportar PDF",
                pdf_data,
                f"reporte_pystreamflow_{datetime.now().strftime('%Y%m%d')}.pdf",
                "application/pdf",
                use_container_width=True,
                key="export_pdf_btn",
            )

    t1, t2 = st.tabs(["📊 Comparativa Mensual", "🥧 Distribución"])

    with t1:
        st.markdown("### Ingresos vs Gastos por mes")

        df_temp = df.copy()
        df_temp["fecha_dt"] = pd.to_datetime(df_temp["fecha"])

        if len(df_temp) < 3:
            st.warning("⚠️ Pocas transacciones. Los gráficos pueden no reflejar tendencias claras.")

        df_temp["mes"] = df_temp["fecha_dt"].dt.strftime("%b %Y")
        comp = df_temp.groupby(["mes", "tipo"])["monto"].sum().reset_index()

        if comp.empty:
            st.info("No hay suficientes datos para mostrar comparativa mensual.")
        else:
            comp["mes_dt"] = pd.to_datetime(comp["mes"], format="%b %Y")
            comp = comp.sort_values("mes_dt")

            fig = px.bar(
                comp,
                x="mes",
                y="monto",
                color="tipo",
                barmode="group",
                color_discrete_map={
                    "Ingreso": COLORES["ingreso"],
                    "Gasto": COLORES["gasto"],
                },
                labels={
                    "mes": "",
                    "monto": f"Monto ({MONEDAS[moneda]['simbolo']})",
                    "tipo": "",
                },
                title="",
            )

            fig.update_layout(
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=COLORES["texto"], size=12),
                xaxis=dict(gridcolor="#334155", tickangle=-30, title="", type="category"),
                yaxis=dict(
                    gridcolor="#334155",
                    title=f"Monto ({MONEDAS[moneda]['simbolo']})",
                    tickprefix=MONEDAS[moneda]["simbolo"] + " ",
                ),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="center",
                    x=0.5,
                    bgcolor="rgba(0,0,0,0)",
                    font=dict(color=COLORES["texto"]),
                ),
                margin=dict(l=40, r=40, t=60, b=80),
                height=400,
            )

            if len(comp) <= 6:
                fig.update_traces(texttemplate="%{y:,.0f}", textposition="outside")

            st.plotly_chart(fig, use_container_width=True)

            with st.expander("📊 Ver tabla de resumen mensual"):
                tabla = comp.pivot(index="mes", columns="tipo", values="monto").fillna(0)
                tabla["Balance"] = tabla.get("Ingreso", 0) - tabla.get("Gasto", 0)
                tabla = tabla.reset_index()

                # Formatear columnas numéricas manteniendo valores originales para filtrado
                tabla_display = tabla.copy()
                for col in ["Ingreso", "Gasto", "Balance"]:
                    if col in tabla_display.columns:
                        tabla_display[col] = tabla_display[col].apply(
                            lambda x: formatear_monto(x, moneda)
                        )

                # Filtro por monto mínimo
                col1, col2 = st.columns(2)
                with col1:
                    min_monto = st.number_input(
                        "Filtrar por monto mínimo",
                        min_value=0.0,
                        value=0.0,
                        step=1000.0,
                        key="filtro_monto_min",
                    )

                # Filtrar tabla original (numérica) y luego formatear
                if min_monto > 0:
                    mask = (tabla["Ingreso"] >= min_monto) | (tabla["Gasto"] >= min_monto)
                    tabla_filtrada = tabla[mask].copy()
                    tabla_display_filtrada = tabla_display[mask].copy()
                else:
                    tabla_filtrada = tabla.copy()
                    tabla_display_filtrada = tabla_display.copy()

                st.dataframe(
                    tabla_display_filtrada,
                    use_container_width=True,
                    hide_index=True,
                    key="tabla_comparativa_mensual",
                )

    with t2:
        col1, col2 = st.columns(2)

        with col1:
            st.markdown(
                f"#### {icon_fa('ingresos_titulo')}Ingresos por categoría",
                unsafe_allow_html=True,
            )
            ing = df[df["tipo"] == "Ingreso"].groupby("categoria")["monto"].sum()
            if not ing.empty:
                fig_ing = px.pie(
                    values=ing.values,
                    names=ing.index,
                    color_discrete_sequence=px.colors.sequential.Greens,
                    hole=0.3,
                )
                fig_ing.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color=COLORES["texto"]),
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=-0.15,
                        font=dict(color=COLORES["texto"]),
                    ),
                    margin=dict(l=20, r=20, t=30, b=60),
                    height=380,
                )
                fig_ing.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig_ing, use_container_width=True)
            else:
                st.info("Sin ingresos")

        with col2:
            st.markdown(
                f"#### {icon_fa('gastos_titulo')}Gastos por categoría",
                unsafe_allow_html=True,
            )
            gas = df[df["tipo"] == "Gasto"].groupby("categoria")["monto"].sum()
            if not gas.empty:
                fig_gas = px.pie(
                    values=gas.values,
                    names=gas.index,
                    color_discrete_sequence=px.colors.sequential.Reds,
                    hole=0.3,
                )
                fig_gas.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    font=dict(color=COLORES["texto"]),
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=-0.15,
                        font=dict(color=COLORES["texto"]),
                    ),
                    margin=dict(l=20, r=20, t=30, b=60),
                    height=380,
                )
                fig_gas.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fig_gas, use_container_width=True)
            else:
                st.info("Sin gastos")


def vista_presupuestos():
    st.markdown("# 🎯 Presupuestos Mensuales")
    st.markdown("---")

    col1, col2 = st.columns([3, 1])
    with col1:
        año_mes = st.session_state.mes_presupuesto.split("-")
        fecha_actual = datetime(int(año_mes[0]), int(año_mes[1]), 1)

        fecha_seleccionada = st.date_input(
            "Mes",
            value=fecha_actual,
            min_value=datetime(2020, 1, 1),
            max_value=datetime.now() + timedelta(days=365),
            format="YYYY/MM/DD",
            key="selector_mes",
        )

        mes_seleccionado = fecha_seleccionada.strftime("%Y-%m")

    if mes_seleccionado != st.session_state.mes_presupuesto:
        st.session_state.mes_presupuesto = mes_seleccionado
        st.rerun()

    df = get_df()
    gastos_mes = {}

    if not df.empty:
        df["fecha_dt"] = pd.to_datetime(df["fecha"])
        df_mes = df[
            (df["fecha_dt"].dt.strftime("%Y-%m") == mes_seleccionado) & (df["tipo"] == "Gasto")
        ]
        gastos_mes = df_mes.groupby("categoria")["monto"].sum().to_dict()

    st.markdown("---")

    st.markdown("### ➕ Agregar nuevo presupuesto")
    with st.form("nuevo_presupuesto"):
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            categoria = st.selectbox(
                "Categoría",
                options=CATEGORIAS["Gasto"] + ["Otros"],
                key="pres_categoria",
            )
        with col2:
            limite = st.number_input(
                "Límite mensual",
                min_value=0.0,
                step=100.0,
                format="%.2f",
                key="pres_limite",
            )
        with col3:
            submitted = st.form_submit_button("💾 Guardar", use_container_width=True)

            if submitted:
                if limite > 0:
                    st.session_state.presupuestos[categoria] = {
                        "limite": limite,
                        "gastado": gastos_mes.get(categoria, 0),
                    }
                    database.guardar_presupuesto(categoria, limite)
                    st.success(f"✅ Presupuesto para {categoria}: {formatear_monto(limite)}")
                    st.rerun()

    st.markdown("---")

    if st.session_state.presupuestos:
        st.markdown("### 📊 Presupuestos activos")

        for categoria, datos in list(st.session_state.presupuestos.items()):
            limite = datos["limite"]
            gastado = gastos_mes.get(categoria, 0)
            restante = limite - gastado
            porcentaje = (gastado / limite * 100) if limite > 0 else 0

            if porcentaje >= 100:
                color_progreso = COLORES["gasto"]
                estado = f"{icon_fa('presupuesto_alert')} Excedido"
            elif porcentaje >= 80:
                color_progreso = COLORES["balance_neg"]
                estado = f"{icon_fa('presupuesto_warn')} Cerca del límite"
            else:
                color_progreso = COLORES["ingreso"]
                estado = f"{icon_fa('presupuesto_ok')} Dentro del presupuesto"

            with st.container():
                st.markdown(
                    f"""
                <div class="budget-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <div>
                            <span style="font-size: 1.2rem; font-weight: 600; color: {COLORES["texto"]};">{categoria}</span>
                            <span style="color: {COLORES["texto_sec"]}; margin-left: 12px;">{estado}</span>
                        </div>
                        <div style="font-weight: 600; color: {color_progreso};">
                            {formatear_monto(gastado)} / {formatear_monto(limite)}
                        </div>
                    </div>
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: {min(porcentaje, 100)}%; background-color: {color_progreso};"></div>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px;">
                        <span style="color: {COLORES["texto_sec"]};">Restante: {formatear_monto(max(restante, 0))}</span>
                        <span style="color: {COLORES["texto_sec"]};">{porcentaje:.1f}% utilizado</span>
                    </div>
                </div>
                """,
                    unsafe_allow_html=True,
                )

                if st.button("Eliminar", key=f"del_pres_{categoria}", icon="🗑️"):
                    del st.session_state.presupuestos[categoria]
                    database.eliminar_presupuesto(categoria)
                    st.rerun()
    else:
        st.info("💡 No hay presupuestos configurados. Agrega uno usando el formulario de arriba.")


# ============================
# NAVEGACIÓN
# ============================


def sidebar():
    with st.sidebar:
        # Header con logo y versión
        st.markdown(
            f"""
        <div style="text-align: center; padding: 20px 0;">
            <h1 style="margin: 0; font-size: 1.5rem;"><i class="fas fa-wallet" style="color: {COLORES["primario"]};"></i> PyStreamFlow</h1>
            <p style="margin: 5px 0 0 0; color: {COLORES["texto_sec"]}; font-size: 0.875rem;">
                Gestión Financiera
            </p>
        </div>
        """,
            unsafe_allow_html=True,
        )

        # Información de usuario y modo
        if st.session_state.get("username"):
            modo = (
                f"{icon_fa('offline')} Offline"
                if st.session_state.get("modo_offline")
                else f"{icon_fa('online')} Supabase"
            )
            st.markdown(f"**👤 {st.session_state.username}** | {modo}", unsafe_allow_html=True)
            if st.button("Cerrar Sesión", use_container_width=True, icon="🚪"):
                st.session_state.logged_in = False
                st.session_state.user_id = None
                st.session_state.username = None
                st.session_state.transacciones = []
                st.session_state.presupuestos = {}
                st.session_state.metas_ahorro = {}
                st.session_state.datos_cargados = False
                st.rerun()

        st.markdown("---")

        # Indicador de moneda (fijo en ARS)
        st.markdown("### 💰 Moneda")
        st.info("🇦🇷 Pesos Argentinos (ARS)")

        st.markdown("---")

        # Período de filtros
        st.markdown("### 📅 Período")

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            fi = st.date_input(
                "Desde",
                pd.to_datetime(st.session_state.filtro_fecha_inicio),
                key="sidebar_fecha_inicio",
            )
        with col_f2:
            ff = st.date_input(
                "Hasta",
                pd.to_datetime(st.session_state.filtro_fecha_fin),
                key="sidebar_fecha_fin",
            )

        if fi.strftime("%Y-%m-%d") != st.session_state.filtro_fecha_inicio:
            if fi > ff:
                st.error("⚠️ La fecha 'Desde' no puede ser mayor que 'Hasta'")
            else:
                st.session_state.filtro_fecha_inicio = fi.strftime("%Y-%m-%d")
                database.guardar_config(
                    st.session_state.moneda_activa,
                    st.session_state.filtro_fecha_inicio,
                    st.session_state.filtro_fecha_fin,
                )
                st.rerun()

        if ff.strftime("%Y-%m-%d") != st.session_state.filtro_fecha_fin:
            if ff < fi:
                st.error("⚠️ La fecha 'Hasta' no puede ser menor que 'Desde'")
            else:
                st.session_state.filtro_fecha_fin = ff.strftime("%Y-%m-%d")
                database.guardar_config(
                    st.session_state.moneda_activa,
                    st.session_state.filtro_fecha_inicio,
                    st.session_state.filtro_fecha_fin,
                )
                st.rerun()

        # Estadísticas rápidas
        st.markdown("---")

        # Gestión de categorías custom
        with st.expander("🏷️ Categorías Custom"):
            st.markdown("**Agregar categoría personalizada**")
            col_cat1, col_cat2 = st.columns(2)
            with col_cat1:
                tipo_custom = st.selectbox("Tipo", ["Ingreso", "Gasto"], key="tipo_custom")
            with col_cat2:
                nueva_cat = st.text_input("Nombre", key="nueva_cat_input")
            if st.button("Agregar", key="agregar_cat_custom"):
                if nueva_cat.strip():
                    guardar_categoria_custom(tipo_custom, nueva_cat.strip())
                    st.success(f"✅ Categoría '{nueva_cat}' agregada")
                    st.rerun()

            # Mostrar categorías custom actuales
            if st.session_state.get("categorias_custom"):
                st.markdown("**Tus categorías custom:**")
                for tipo, cats in st.session_state.categorias_custom.items():
                    if cats:
                        st.markdown(f"- **{tipo}**: {', '.join(cats)}")

        st.markdown("---")

        # Asistente IA destacado
        st.markdown(
            """
        <div class="ia-featured-card">
            <div class="ia-chat-header">
                <div class="ia-chat-icon">🤖</div>
                <div>
                    <h3 class="ia-chat-title">Asistente IA</h3>
                    <p class="ia-chat-subtitle">Preguntame sobre tus finanzas</p>
                </div>
            </div>
        </div>
        """,
            unsafe_allow_html=True,
        )

        consultas_rapidas = [
            "¿Cuánto gasté esta semana?",
            "¿Cuál es mi mayor gasto?",
            "¿Cuánto me queda de presupuesto?",
            "¿Cuánto he ahorrado?",
        ]
        for consulta in consultas_rapidas:
            if st.button(f"💬 {consulta}", key=f"quick_{consulta[:10]}", use_container_width=True):
                contexto = obtener_contexto_financiero()
                with st.spinner("🤖 Pensando..."):
                    respuesta = consultar_ia(consulta, contexto)
                st.session_state["ia_respuesta_temp"] = respuesta
                st.rerun()

        if st.session_state.get("ia_respuesta_temp"):
            with st.container():
                st.markdown(
                    """
                <div class="ia-response">
                    <strong>🤖 Respuesta:</strong>
                </div>
                """,
                    unsafe_allow_html=True,
                )
                st.markdown(st.session_state["ia_respuesta_temp"])
                st.markdown("---")
                if st.button("🔄 Nueva pregunta", key="clean_ia", use_container_width=True):
                    del st.session_state["ia_respuesta_temp"]
                    st.rerun()

        st.markdown("---")
        st.markdown("### 📊 Resumen")

        total = len(st.session_state.transacciones)
        df = get_df()
        if not df.empty:
            met = calcular_metricas(df)
            st.metric("Total transacciones", f"{total}")
            st.metric("Balance actual", formatear_monto(met["balance"]))

        st.markdown("---")
        st.markdown(
            f"<p style='text-align: center; color: {COLORES['texto_sec']}; font-size: 0.75rem;'>v4.0 · <i class='fab fa-python'></i> Streamlit</p>",
            unsafe_allow_html=True,
        )


# ============================
# MAIN
# ============================


def render_top_nav():
    """Renderiza la barra de navegación superior con botones uniformes sin efecto de clic"""
    vista_actual = st.session_state.vista

    # CSS personalizado para la barra de navegación
    st.markdown(
        """
    <style>
    /* Contenedor de la barra de navegación */
    .nav-container {
        display: flex;
        justify-content: center;
        gap: 8px;
        margin: 8px 0 16px 0;
        padding: 4px 0;
        border-bottom: 1px solid rgba(255,255,255,0.1);
    }
    
    /* Estilo base para todos los botones de navegación */
    .nav-btn {
        flex: 1;
        max-width: 160px;
        text-align: center;
        padding: 12px 16px !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        transition: all 0.2s ease !important;
        cursor: pointer;
        border: none !important;
        background: transparent !important;
        color: #94a3b8 !important;
        transform: none !important;
        box-shadow: none !important;
        outline: none !important;
        white-space: nowrap !important;
    }
    
    /* Eliminar efecto de "achicamiento" al hacer clic */
    .nav-btn:active,
    .nav-btn:focus {
        transform: scale(1) !important;
        box-shadow: none !important;
        outline: none !important;
    }
    
    /* Hover para botones inactivos */
    .nav-btn:hover:not(.nav-btn-active) {
        background: rgba(99, 102, 241, 0.1) !important;
        color: #f8fafc !important;
    }
    
    /* Botón activo */
    .nav-btn-active {
        background: linear-gradient(135deg, #6366F1, #8B5CF6) !important;
        color: white !important;
        box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3) !important;
    }
    
    /* Forzar ancho uniforme en todas las columnas */
    .nav-container > div {
        flex: 1;
        min-width: 0;
        display: flex;
        justify-content: center;
    }
    
    /* Asegurar que los botones ocupen el ancho disponible */
    .nav-container .stButton {
        width: 100%;
        max-width: 160px;
    }
    
    .nav-container .stButton button {
        width: 100% !important;
        justify-content: center !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        background: transparent !important;
        color: #94a3b8 !important;
        border: none !important;
        transform: none !important;
        box-shadow: none !important;
        padding: 12px 16px !important;
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.95rem !important;
        transition: all 0.2s ease !important;
    }
    
    .nav-container .stButton button:hover {
        background: rgba(99, 102, 241, 0.1) !important;
        color: #f8fafc !important;
    }
    
    .nav-container .stButton button:active,
    .nav-container .stButton button:focus {
        transform: scale(1) !important;
        box-shadow: none !important;
        outline: none !important;
    }
    
    /* Responsive */
    @media (max-width: 768px) {
        .nav-container {
            flex-wrap: wrap;
            gap: 4px;
        }
        .nav-container > div {
            min-width: calc(50% - 4px);
            flex: 1 1 auto;
        }
        .nav-btn,
        .nav-container .stButton button {
            padding: 10px 8px !important;
            font-size: 0.85rem !important;
        }
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # Barra de navegación con botones personalizados
    opciones_nav = [
        ("📊", "Dashboard"),
        ("➕", "Nueva"),
        ("📋", "Historial"),
        ("📈", "Gráficos"),
        ("💰", "Presupuestos"),
        ("🎯", "Metas"),
        ("📦", "Migrar"),
    ]

    cols = st.columns(len(opciones_nav))
    for i, (icono, nombre) in enumerate(opciones_nav):
        with cols[i]:
            es_activo = vista_actual == nombre
            if st.button(
                f"{icono} {nombre}",
                key=f"nav_{nombre}",
                use_container_width=True,
                type="primary" if es_activo else "secondary",
            ):
                st.session_state.vista = nombre
                st.rerun()

    # Separador visual
    st.markdown("<hr style='margin: 12px 0 20px 0; opacity: 0.2;'>", unsafe_allow_html=True)


def vista_migrar():
    """Vista para migrar (exportar/importar) datos de transacciones y presupuestos"""
    st.markdown("# 🔄 Migrar Datos")
    st.markdown("---")

    st.markdown("""
    Esta sección te permite **exportar** tus datos a un archivo de respaldo 
    e **importar** datos desde un archivo de respaldo previo.
    
    **Formato:** JSON (incluye transacciones y presupuestos)
    """)

    st.markdown("---")

    # Sección de Exportación
    st.markdown("### 📤 Exportar Datos")

    col1, col2 = st.columns([1, 2])
    with col1:
        if st.button("Generar Backup", use_container_width=True, type="primary", icon="📦"):
            # Crear diccionario con todos los datos
            backup_data = {
                "version": "1.0",
                "fecha_exportacion": datetime.now().isoformat(),
                "usuario": st.session_state.get("username", "local"),
                "transacciones": st.session_state.transacciones,
                "presupuestos": st.session_state.presupuestos,
                "metas_ahorro": st.session_state.metas_ahorro,
                "moneda_activa": st.session_state.moneda_activa,
                "filtro_fecha_inicio": st.session_state.filtro_fecha_inicio,
                "filtro_fecha_fin": st.session_state.filtro_fecha_fin,
            }

            # Convertir a JSON
            import json

            backup_json = json.dumps(backup_data, indent=2, ensure_ascii=False)

            # Botón de descarga
            st.download_button(
                label="📥 Descargar Backup JSON",
                data=backup_json,
                file_name=f"pystreamflow_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
            )

            st.success(
                f"✅ Backup generado con {len(st.session_state.transacciones)} transacciones y {len(st.session_state.presupuestos)} presupuestos"
            )

    with col2:
        st.info("El backup incluye todas tus transacciones, presupuestos y configuraciones.")

    st.markdown("---")

    # Sección de Importación
    st.markdown("### 📥 Importar Datos")

    uploaded_file = st.file_uploader(
        "Selecciona un archivo de backup JSON",
        type=["json"],
        help="Sube un archivo .json previamente exportado",
    )

    if uploaded_file is not None:
        try:
            import json

            backup_data = json.load(uploaded_file)

            # Validar estructura del archivo
            if "transacciones" not in backup_data or "presupuestos" not in backup_data:
                st.error("❌ Archivo inválido: no contiene la estructura esperada")
            else:
                # Mostrar resumen del backup
                st.markdown("#### Resumen del Backup")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Transacciones", len(backup_data["transacciones"]))
                with col2:
                    st.metric("Presupuestos", len(backup_data["presupuestos"]))
                with col3:
                    st.metric("Usuario", backup_data.get("usuario", "Desconocido"))

                st.markdown("#### Opciones de Importación")

                import_mode = st.radio(
                    "Modo de importación:",
                    options=[
                        "🔄 Reemplazar todo (borra datos actuales)",
                        "➕ Agregar nuevos (mantiene datos actuales)",
                    ],
                    help="Reemplazar borrará tus datos actuales. Agregar solo añadirá los nuevos.",
                )

                if st.button("Confirmar Importación", type="primary", icon="📤"):
                    if "Reemplazar todo" in import_mode:
                        st.session_state.transacciones = backup_data["transacciones"]
                        st.session_state.presupuestos = backup_data["presupuestos"]
                        st.session_state.metas_ahorro = backup_data.get("metas_ahorro", {})
                        st.session_state.moneda_activa = backup_data.get("moneda_activa", "ARS")
                        st.session_state.filtro_fecha_inicio = backup_data.get(
                            "filtro_fecha_inicio", st.session_state.filtro_fecha_inicio
                        )
                        st.session_state.filtro_fecha_fin = backup_data.get(
                            "filtro_fecha_fin", st.session_state.filtro_fecha_fin
                        )

                        database.importar_backup(backup_data, "reemplazar")

                        st.success(
                            f"✅ Datos reemplazados: {len(backup_data['transacciones'])} transacciones, {len(backup_data['presupuestos'])} presupuestos y {len(backup_data.get('metas_ahorro', {}))} metas importadas"
                        )

                    else:  # Agregar nuevos
                        existing_ids = {t["id"] for t in st.session_state.transacciones}

                        nuevas_transacciones = [
                            t for t in backup_data["transacciones"] if t["id"] not in existing_ids
                        ]

                        st.session_state.transacciones.extend(nuevas_transacciones)

                        st.session_state.presupuestos.update(backup_data["presupuestos"])

                        st.session_state.metas_ahorro.update(backup_data.get("metas_ahorro", {}))

                        database.importar_backup(backup_data, "agregar")

                        st.success(
                            f"✅ Datos agregados: {len(nuevas_transacciones)} transacciones nuevas, {len(backup_data['presupuestos'])} presupuestos y {len(backup_data.get('metas_ahorro', {}))} metas"
                        )

                    st.rerun()

        except json.JSONDecodeError:
            st.error("❌ Error al leer el archivo: formato JSON inválido")
        except Exception as e:
            st.error(f"❌ Error al procesar el archivo: {str(e)}")

    st.markdown("---")

    # Sección de ayuda
    with st.expander("📖 Ayuda: Formato del archivo de backup"):
        st.markdown("""
        **Estructura del archivo JSON:**
        
        ```json
        {
          "version": "1.0",
          "fecha_exportacion": "2024-01-01T12:00:00",
          "usuario": "nombre_usuario",
          "transacciones": [
            {
              "id": "txn_20240101120000123456",
              "tipo": "Ingreso",
              "monto": 15000,
              "categoria": "Salario",
              "descripcion": "Sueldo enero",
              "fecha": "2024-01-01",
              "moneda": "ARS"
            }
          ],
          "presupuestos": {
            "Comida": 50000,
            "Transporte": 20000
          }
        }
        ```
        
        **Nota:** No modifiques manualmente el archivo JSON a menos que sepas lo que estás haciendo.
        """)


def vista_metas():
    """Vista para gestionar metas de ahorro"""
    st.markdown("# 🎯 Metas de Ahorro")
    st.markdown("---")

    st.markdown("""
    Establece metas de ahorro y monitorea tu progreso hacia ellas.
    """)

    # Sección para crear nueva meta
    st.markdown("### ➕ Nueva Meta")

    with st.form(key="form_nueva_meta"):
        col1, col2 = st.columns(2)
        with col1:
            nombre_meta = st.text_input(
                "Nombre de la meta", placeholder="Ej: Vacaciones, Auto, Casa"
            )
        with col2:
            monto_objetivo = st.number_input(
                "Monto objetivo",
                min_value=0.0,
                step=1000.0,
                format="%.2f",
                placeholder="Ej: 500000",
            )

        col3, col4 = st.columns(2)
        with col3:
            fecha_limite = st.date_input("Fecha límite", value=datetime.now() + timedelta(days=365))
        with col4:
            categoria = st.selectbox(
                "Categoría",
                [
                    "Viajes",
                    "Vehículo",
                    "Vivienda",
                    "Educación",
                    "Emergencia",
                    "Inversión",
                    "Otro",
                ],
            )

        submitted = st.form_submit_button(
            "💾 Guardar Meta", type="primary", use_container_width=True
        )

        if submitted:
            if nombre_meta and monto_objetivo > 0:
                meta_id = f"meta_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                nueva_meta = {
                    "id": meta_id,
                    "nombre": nombre_meta,
                    "objetivo": monto_objetivo,
                    "ahorrado": 0.0,
                    "fecha_limite": fecha_limite.strftime("%Y-%m-%d"),
                    "categoria": categoria,
                    "fecha_creacion": datetime.now().strftime("%Y-%m-%d"),
                }
                st.session_state.metas_ahorro[meta_id] = nueva_meta
                database.guardar_meta(nueva_meta)

                if (
                    st.session_state.logged_in
                    and st.session_state.user_id
                    and not st.session_state.get("modo_offline", False)
                ):
                    try:
                        auth.guardar_metas_ahorro(
                            st.session_state.user_id, st.session_state.metas_ahorro
                        )
                    except Exception as e:
                        st.warning(f"No se pudo guardar en Supabase: {e}")

                st.success(f"✅ Meta '{nombre_meta}' creada exitosamente")
                st.rerun()
            else:
                st.warning("Por favor completa el nombre y el monto objetivo")

    st.markdown("---")

    # Sección para listar metas
    st.markdown("### 📋 Metas Activas")

    if not st.session_state.metas_ahorro:
        st.info("No hay metas de ahorro creadas aún. ¡Crea tu primera meta!")
    else:
        # Calcular total ahorrado y total objetivo
        total_ahorrado = sum(
            meta.get("ahorrado", 0) for meta in st.session_state.metas_ahorro.values()
        )
        total_objetivo = sum(
            meta.get("objetivo", 0) for meta in st.session_state.metas_ahorro.values()
        )

        # Mostrar resumen
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Objetivo", formatear_monto(total_objetivo))
        with col2:
            st.metric("Total Ahorrado", formatear_monto(total_ahorrado))
        with col3:
            progreso_total = (total_ahorrado / total_objetivo * 100) if total_objetivo > 0 else 0
            st.metric("Progreso Global", f"{progreso_total:.1f}%")

        st.markdown("---")

        # Listar cada meta
        for meta_id, meta in st.session_state.metas_ahorro.items():
            with st.container():
                # Calcular progreso
                objetivo = meta.get("objetivo", 0)
                ahorrado = meta.get("ahorrado", 0)
                progreso = (ahorrado / objetivo * 100) if objetivo > 0 else 0
                restante = objetivo - ahorrado

                # Determinar color del progreso
                if progreso >= 100:
                    color_progreso = COLORES["ingreso"]
                    estado = "✅ Completada"
                elif progreso >= 70:
                    color_progreso = COLORES["balance_pos"]
                    estado = "🎯 Cerca de la meta"
                elif progreso >= 30:
                    color_progreso = COLORES["balance_neg"]
                    estado = "📊 En progreso"
                else:
                    color_progreso = COLORES["gasto"]
                    estado = "⏳ Iniciando"

                # Mostrar tarjeta de meta
                st.markdown(
                    f"""
                <div style="
                    background: rgba(30, 41, 59, 0.5);
                    backdrop-filter: blur(10px);
                    border: 1px solid rgba(255,255,255,0.1);
                    border-radius: 16px;
                    padding: 20px;
                    margin-bottom: 16px;
                ">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <div>
                            <span style="font-size: 1.1rem; font-weight: 600; color: {COLORES["texto"]};">
                                {meta["nombre"]}
                            </span>
                            <span style="color: {COLORES["texto_sec"]}; margin-left: 12px; font-size: 0.9rem;">
                                {meta["categoria"]}
                            </span>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-weight: 700; color: {color_progreso}; font-size: 1.1rem;">
                                {formatear_monto(ahorrado)} / {formatear_monto(objetivo)}
                            </div>
                            <div style="color: {COLORES["texto_sec"]}; font-size: 0.85rem;">
                                {estado}
                            </div>
                        </div>
                    </div>
                    <div style="background: rgba(255,255,255,0.1); border-radius: 8px; height: 12px; margin-bottom: 8px;">
                        <div style="
                            background: {color_progreso};
                            border-radius: 8px;
                            height: 100%;
                            width: {min(progreso, 100)}%;
                            transition: width 0.3s ease;
                        "></div>
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; color: {COLORES["texto_sec"]}; font-size: 0.85rem;">
                        <span>📅 Fecha límite: {meta["fecha_limite"]}</span>
                        <span>💰 Restante: {formatear_monto(restante)}</span>
                    </div>
                </div>
                """,
                    unsafe_allow_html=True,
                )

                # Acciones para cada meta
                col_accion1, col_accion2, col_accion3 = st.columns([2, 1, 1])
                with col_accion1:
                    nuevo_ahorro = st.number_input(
                        "Añadir ahorro",
                        min_value=0.0,
                        step=1000.0,
                        key=f"ahorro_{meta_id}",
                        label_visibility="collapsed",
                    )
                with col_accion2:
                    if st.button(
                        "Añadir",
                        key=f"add_{meta_id}",
                        use_container_width=True,
                        icon="➕",
                    ):
                        if nuevo_ahorro > 0:
                            st.session_state.metas_ahorro[meta_id]["ahorrado"] += nuevo_ahorro
                            database.guardar_meta(st.session_state.metas_ahorro[meta_id])
                            if (
                                st.session_state.logged_in
                                and st.session_state.user_id
                                and not st.session_state.get("modo_offline", False)
                            ):
                                try:
                                    auth.guardar_metas_ahorro(
                                        st.session_state.user_id,
                                        st.session_state.metas_ahorro,
                                    )
                                except Exception as e:
                                    st.warning(f"No se pudo guardar en Supabase: {e}")

                            st.success(
                                f"✅ Añadido {formatear_monto(nuevo_ahorro)} a '{meta['nombre']}'"
                            )
                            st.rerun()
                with col_accion3:
                    if st.button(
                        "Eliminar",
                        key=f"del_{meta_id}",
                        use_container_width=True,
                        icon="🗑️",
                    ):
                        del st.session_state.metas_ahorro[meta_id]
                        database.eliminar_meta(meta_id)
                        if (
                            st.session_state.logged_in
                            and st.session_state.user_id
                            and not st.session_state.get("modo_offline", False)
                        ):
                            try:
                                auth.guardar_metas_ahorro(
                                    st.session_state.user_id,
                                    st.session_state.metas_ahorro,
                                )
                            except Exception as e:
                                st.warning(f"No se pudo guardar en Supabase: {e}")
                        st.rerun()

                st.markdown("---")

    # Sección de ayuda
    with st.expander("📖 Consejos para ahorrar"):
        st.markdown("""
        **💡 Consejos útiles:**
        
        1. **Establece metas realistas**: Comienza con metas alcanzables para mantenerte motivado.
        2. **Divide grandes metas**: Si tu meta es muy grande, divídela en hitos más pequeños.
        3. **Automatiza tus ahorros**: Configura transferencias automáticas a tu cuenta de ahorros.
        4. **Revisa periódicamente**: Actualiza tus metas según tu progreso y cambia en tus ingresos.
        
        **📊 Fórmula de progreso:**
        ```
        Progreso = (Ahorrado / Objetivo) × 100
        ```
        """)


def render_breadcrumbs():
    """Renderiza breadcrumbs basados en la vista actual"""
    vista_actual = st.session_state.vista

    iconos_breadcrumbs = {
        "Inicio": "🏠",
        "Dashboard": "📊",
        "Nueva": "➕",
        "Historial": "📋",
        "Gráficos": "📈",
        "Presupuestos": "💰",
        "Metas": "🎯",
        "Migrar": "🔄",
    }

    if vista_actual == "Dashboard":
        breadcrumbs = [("Inicio", "Dashboard"), ("Dashboard", None)]
    elif vista_actual == "Nueva":
        breadcrumbs = [("Inicio", "Dashboard"), ("Nueva", None)]
    elif vista_actual == "Historial":
        breadcrumbs = [("Inicio", "Dashboard"), ("Historial", None)]
    elif vista_actual == "Gráficos":
        breadcrumbs = [("Inicio", "Dashboard"), ("Gráficos", None)]
    elif vista_actual == "Presupuestos":
        breadcrumbs = [("Inicio", "Dashboard"), ("Presupuestos", None)]
    elif vista_actual == "Migrar":
        breadcrumbs = [("Inicio", "Dashboard"), ("Migrar", None)]
    elif vista_actual == "Metas":
        breadcrumbs = [("Inicio", "Dashboard"), ("Metas", None)]
    else:
        breadcrumbs = [("Inicio", "Dashboard")]

    # Renderizar breadcrumbs de forma compacta
    breadcrumb_html = '<div class="breadcrumbs">'
    for i, (nombre, vista_link) in enumerate(breadcrumbs):
        icono = iconos_breadcrumbs.get(nombre, "")
        if vista_link:
            breadcrumb_html += f'<a href="#" onclick="return false;">{icono} {nombre}</a>'
        else:
            breadcrumb_html += (
                f'<span style="color: #f8fafc; font-weight: 600;">{icono} {nombre}</span>'
            )
        if i < len(breadcrumbs) - 1:
            breadcrumb_html += '<span class="breadcrumbs-separator">›</span>'
    breadcrumb_html += "</div>"

    st.markdown(breadcrumb_html, unsafe_allow_html=True)


def main():
    st.set_page_config(page_title="PyStreamFlow", page_icon="💰", layout="wide")

    # PWA Support
    st.markdown(
        """
        <link rel="manifest" href="/static/manifest.json">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
        <meta name="apple-mobile-web-app-title" content="PyStreamFlow">
        <meta name="application-name" content="PyStreamFlow">
        <meta name="mobile-web-app-capable" content="yes">
        <meta name="theme-color" content="#6366F1">
        <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect fill='%236366F1' width='100' height='100' rx='20'/><text y='65' x='50' text-anchor='middle' font-size='50'>💰</text></svg>">
    """,
        unsafe_allow_html=True,
    )

    init_state()
    css()

    # Atajos de teclado
    st.markdown(
        """
    <script>
    document.addEventListener('keydown', function(e) {
        if (e.ctrlKey || e.metaKey) {
            if (e.key === 'n' || e.key === 'N') {
                e.preventDefault();
                window.streamlitValue = "Nueva";
            } else if (e.key === 'h' || e.key === 'H') {
                e.preventDefault();
                window.streamlitValue = "Historial";
            } else if (e.key === 'd' || e.key === 'D') {
                e.preventDefault();
                window.streamlitValue = "Dashboard";
            }
        }
    });
    </script>
    """,
        unsafe_allow_html=True,
    )

    if not st.session_state.logged_in:
        render_auth_screen()
        return

    # Renderizar barra de navegación superior
    render_top_nav()

    # Renderizar breadcrumbs
    render_breadcrumbs()

    sidebar()

    cargar_datos_usuario()

    # Contenedor principal con transición suave
    with st.container():
        st.markdown('<div class="view-fade-in">', unsafe_allow_html=True)

        vistas = {
            "Dashboard": vista_dashboard,
            "Nueva": vista_nueva,
            "Historial": vista_historial,
            "Gráficos": vista_graficos,
            "Presupuestos": vista_presupuestos,
            "Metas": vista_metas,
            "Migrar": vista_migrar,
        }

        vistas.get(st.session_state.vista, vista_dashboard)()

        st.markdown("</div>", unsafe_allow_html=True)


def render_auth_screen():
    st.markdown(
        """
    <style>
    .auth-container {
        max-width: 400px;
        margin: 50px auto;
        padding: 30px;
        background: rgba(30, 41, 59, 0.8);
        border-radius: 15px;
        backdrop-filter: blur(10px);
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🔐 PyStreamFlow")
        st.markdown("### Bienvenido")

        tab_local, tab_cloud = st.tabs(["🏠 Modo Local", "☁️ Login Cloud"])

        with tab_local:
            st.markdown("""
            **✅ Sin registro requerido**
            
            Usa modo local para:
            - 💾 Datos guardados en tu PC
            - 🔒 Sin compartir datos
            - ⚡ Acceso inmediato
            """)

            if st.button(
                "🚀 Continuar en Modo Local", type="primary", use_container_width=True, icon="🏠"
            ):
                st.session_state.logged_in = True
                st.session_state.user_id = None
                st.session_state.username = "local"
                st.session_state.modo_offline = True
                st.rerun()

        with tab_cloud:
            st.info("☁️ Requiere configurar Supabase en variables de entorno")

            username = st.text_input("Usuario", key="login_user")
            password = st.text_input("Contraseña", type="password", key="login_pass")

            if st.button("Iniciar Sesión", type="primary", use_container_width=True, icon="🔑"):
                if username and password:
                    try:
                        resultado = auth.login_usuario(username, password)
                        if resultado["success"]:
                            st.session_state.logged_in = True
                            st.session_state.user_id = resultado["user_id"]
                            st.session_state.username = resultado["username"]
                            st.session_state.modo_offline = False
                            st.rerun()
                        else:
                            st.error(resultado["error"])
                    except Exception as e:
                        st.error(f"Error de conexión: {e}")
                else:
                    st.warning("Completa todos los campos")

            new_username = st.text_input("Nuevo usuario", key="reg_user")
            new_password = st.text_input("Nueva contraseña", type="password", key="reg_pass")
            confirm_password = st.text_input(
                "Confirmar contraseña", type="password", key="reg_pass2"
            )

            if st.button("Crear Cuenta", type="primary", use_container_width=True, icon="📝"):
                if new_username and new_password and confirm_password:
                    if new_password != confirm_password:
                        st.error("Las contraseñas no coinciden")
                    else:
                        try:
                            resultado = auth.registrar_usuario(new_username, new_password)
                            if resultado["success"]:
                                st.session_state.logged_in = True
                                st.session_state.user_id = resultado["user_id"]
                                st.session_state.username = resultado["username"]
                                st.session_state.modo_offline = False
                                st.success("¡Cuenta creada!")
                                st.rerun()
                            else:
                                st.error(resultado["error"])
                        except Exception as e:
                            st.error(f"Error: {e}")
                else:
                    st.warning("Completa todos los campos")


if __name__ == "__main__":
    main()
