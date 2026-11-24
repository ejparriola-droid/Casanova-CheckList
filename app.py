import streamlit as st
import pandas as pd
import requests
import re
from io import BytesIO
from datetime import date, datetime

# =====================================
# CONFIGURACIÓN
# =====================================

st.set_page_config(
    page_title="Casanova CheckList",
    page_icon="🚗",
    layout="wide"
)

API_URL = "http://186.96.185.112:4000/api/logUnits/flotaVehicular/download"

COLUMNAS = [
    "Linea",
    "Version",
    "Modelo",
    "Serie",
    "Placa",
    "Fecha Compra",
    "Unidad de Negocio",
    "Nombre Cliente",
    "Almacen"
]

# Requisitos y fechas que se solicitan cuando corresponda.
# La fecha se captura como dato de apoyo; no sustituye la validación documental.
CHECKLIST = {
    "Documentación de circulación": [
        {"nombre": "Tarjeta de circulación vigente", "fecha": "Fecha de vigencia"},
        {"nombre": "Placa delantera"},
        {"nombre": "Placa trasera"},
        {"nombre": "Calcomanía o engomado de circulación"},
        {"nombre": "Permiso provisional para circular (si aplica)", "fecha": "Fecha de vencimiento del permiso"},
    ],
    "Pagos vehiculares": [
        {"nombre": "Tenencia pagada (si aplica)", "fecha": "Fecha de pago de tenencia"},
        {"nombre": "Refrendo vehicular pagado", "fecha": "Fecha de pago de refrendo"},
        {"nombre": "Adeudos de tenencia anteriores"},
        {"nombre": "Multas de tránsito pendientes"},
        {"nombre": "Infracciones vehiculares pendientes"},
    ],
    "Verificación vehicular": [
        {"nombre": "Verificación vehicular vigente", "fecha": "Fecha de vigencia de verificación"},
        {"nombre": "Holograma de verificación"},
        {"nombre": "Constancia de verificación", "fecha": "Fecha de emisión de constancia"},
        {"nombre": "Sin adeudos o restricciones que impidan verificar"},
    ],
    "Seguro vehicular": [
        {"nombre": "Seguro de responsabilidad civil vigente"},
        {"nombre": "Póliza de seguro vigente", "fecha": "Fecha de vigencia de póliza"},
        {"nombre": "Comprobante de pago del seguro", "fecha": "Fecha de pago del seguro"},
        {"nombre": "Fecha de vencimiento del seguro", "fecha": "Fecha de vencimiento del seguro"},
    ],
}

TOTAL_REQUISITOS = sum(len(items) for items in CHECKLIST.values())

# =====================================
# ESTILOS
# =====================================

st.markdown("""
<style>
/* Paleta de alto contraste: solo se modifican colores */
.stApp {
    background-color: #F3F6FA;
    color: #172B4D;
}
h1, h2, h3, h4 {
    color: #163A5F;
}

/* Texto general y etiquetas */
.stMarkdown, label, p, span, div {
    color: inherit;
}

/* Botones */
div.stButton > button,
div.stDownloadButton > button,
button[kind="primary"] {
    background-color: #174A7E;
    color: #FFFFFF;
    border: 1px solid #123B65;
    border-radius: 8px;
    font-weight: bold;
}
div.stButton > button:hover,
div.stDownloadButton > button:hover {
    background-color: #0F355B;
    color: #FFFFFF;
    border-color: #0F355B;
}

/* Tarjetas de indicadores */
div[data-testid="stMetric"] {
    background: #FFFFFF;
    border: 1px solid #C7D2E0;
    color: #172B4D;
    padding: 12px;
    border-radius: 10px;
}

/* Mensajes de estado */
div[data-testid="stAlert"] {
    border: 1px solid #B8C7D9;
}

/* Campos de captura */
input, textarea, [data-baseweb="select"] > div {
    background-color: #FFFFFF;
    color: #172B4D;
}
</style>
""", unsafe_allow_html=True)

# =====================================
# FUNCIONES
# =====================================

@st.cache_data(ttl=300)
def cargar_base():
    respuesta = requests.get(API_URL, timeout=90)
    respuesta.raise_for_status()
    archivo = BytesIO(respuesta.content)

    try:
        df = pd.read_excel(archivo)
    except Exception:
        archivo.seek(0)
        df = pd.read_csv(archivo)

    df.columns = df.columns.astype(str).str.strip()
    faltantes = [col for col in COLUMNAS if col not in df.columns]

    if faltantes:
        raise ValueError(
            "No se encontraron estas columnas: " + ", ".join(faltantes)
        )

    df = df[COLUMNAS].copy()
    df["Serie"] = df["Serie"].astype(str).str.strip()
    df["Nombre Cliente"] = (
        df["Nombre Cliente"].fillna("").astype(str).str.strip()
    )
    df.loc[
        df["Nombre Cliente"].str.upper().isin(
            ["", "SIN INFORMACION", "SIN INFORMACIÓN", "NAN", "NONE"]
        ),
        "Nombre Cliente"
    ] = "SIN CONTRATO"

    return df


def normalizar_serie(valor):
    if pd.isna(valor):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(valor).upper())


def valor_mostrar(valor):
    if pd.isna(valor) or str(valor).strip().lower() in ("", "nan", "none"):
        return "Sin información"
    if isinstance(valor, (datetime, date)):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def inicializar_estado():
    if "checklists_guardados" not in st.session_state:
        st.session_state.checklists_guardados = []


def crear_clave(categoria, indice):
    return f"respuesta_{categoria}_{indice}"


def construir_registro(unidad, respuestas):
    return {
        "fecha_revision": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "serie": str(unidad["Serie"]),
        "placa": valor_mostrar(unidad["Placa"]),
        "linea": valor_mostrar(unidad["Linea"]),
        "modelo": valor_mostrar(unidad["Modelo"]),
        "unidad_negocio": valor_mostrar(unidad["Unidad de Negocio"]),
        "cliente": valor_mostrar(unidad["Nombre Cliente"]),
        "almacen": valor_mostrar(unidad["Almacen"]),
        "respuestas": respuestas,
    }


inicializar_estado()

# =====================================
# ENCABEZADO
# =====================================

st.title("🚗 CASANOVA CHECKLIST")
st.caption("CORPORATIVO | CONTROL DE TRÁMITES VEHICULARES")
st.divider()

# =====================================
# CONEXIÓN CON BASE MAESTRA
# =====================================

col1, col2 = st.columns([3, 1])
with col1:
    st.subheader("Consulta de unidades")
with col2:
    if st.button("🔄 Actualizar base"):
        cargar_base.clear()
        st.rerun()

try:
    df = cargar_base()
    st.success(
        f"Base conectada correctamente | {len(df):,} vehículos disponibles"
    )
except Exception as e:
    st.error(f"No fue posible consultar la base: {e}")
    st.stop()

# =====================================
# BÚSQUEDA
# =====================================

st.markdown("### 🔎 Buscar vehículo")

serie_busqueda = st.text_input(
    "Ingresa los últimos 9 caracteres de la serie",
    max_chars=9,
    placeholder="Ejemplo: KK1234567"
)

if serie_busqueda:
    serie_normalizada = normalizar_serie(serie_busqueda)

    if len(serie_normalizada) != 9:
        st.warning("Debes ingresar exactamente 9 caracteres.")
        st.stop()

    df["_serie_busqueda"] = df["Serie"].apply(normalizar_serie)
    resultados = df[
        df["_serie_busqueda"].str.endswith(serie_normalizada, na=False)
    ].copy()

    if resultados.empty:
        st.error("No encontramos ninguna unidad con esa serie.")
    else:
        st.success(f"Encontramos {len(resultados)} coincidencia(s).")

        if len(resultados) > 1:
            opciones = resultados.index.tolist()
            seleccion = st.selectbox(
                "Encontramos varias unidades. Selecciona la correcta:",
                opciones,
                format_func=lambda i: (
                    f"{resultados.loc[i, 'Serie']} | "
                    f"{resultados.loc[i, 'Linea']} | "
                    f"{resultados.loc[i, 'Placa']}"
                )
            )
        else:
            seleccion = resultados.index[0]

        unidad = resultados.loc[seleccion]

        # =================================
        # DATOS DE LA UNIDAD
        # =================================

        st.divider()
        st.subheader("📋 Información del vehículo")

        c1, c2, c3 = st.columns(3)
        c1.metric("Línea", valor_mostrar(unidad["Linea"]))
        c2.metric("Versión", valor_mostrar(unidad["Version"]))
        c3.metric("Modelo", valor_mostrar(unidad["Modelo"]))

        c1, c2, c3 = st.columns(3)
        c1.metric("Placa", valor_mostrar(unidad["Placa"]))
        c2.metric("Unidad de negocio", valor_mostrar(unidad["Unidad de Negocio"]))
        c3.metric("Cliente", valor_mostrar(unidad["Nombre Cliente"]))

        st.write("**Serie completa:**", valor_mostrar(unidad["Serie"]))
        st.write("**Fecha de compra:**", valor_mostrar(unidad["Fecha Compra"]))
        st.write("**Almacén:**", valor_mostrar(unidad["Almacen"]))

        st.divider()
        st.subheader("📝 Control de trámites")

        st.info(
            "Selecciona SÍ o NO para cada requisito. "
            "Los requisitos marcados como NO se contabilizan como pendientes."
        )

        # Identificador de formulario por unidad para evitar mezclar capturas.
        serie_id = normalizar_serie(unidad["Serie"])
        form_key = f"form_checklist_{serie_id}"

        respuestas = {}
        respondidos = 0
        cumplen = 0
        pendientes = 0

        with st.form(form_key):
            for categoria, requisitos in CHECKLIST.items():
                st.markdown(f"### {categoria}")

                for indice, requisito in enumerate(requisitos):
                    nombre = requisito["nombre"]
                    respuesta_key = crear_clave(categoria, indice)

                    st.markdown(f"**{nombre}**")
                    opciones_respuesta = ["Sin revisar", "Sí", "No"]
                    respuesta = st.radio(
                        f"Resultado: {nombre}",
                        opciones_respuesta,
                        horizontal=True,
                        index=0,
                        key=respuesta_key,
                        label_visibility="collapsed"
                    )

                    fecha_valor = None
                    if requisito.get("fecha"):
                        fecha_valor = st.date_input(
                            requisito["fecha"],
                            value=None,
                            key=f"fecha_{serie_id}_{categoria}_{indice}",
                            format="DD/MM/YYYY"
                        )

                    observacion = st.text_input(
                        "Observaciones (opcional)",
                        key=f"obs_{serie_id}_{categoria}_{indice}"
                    )

                    respuestas[nombre] = {
                        "categoria": categoria,
                        "respuesta": respuesta,
                        "fecha": fecha_valor.isoformat() if fecha_valor else "",
                        "campo_fecha": requisito.get("fecha", ""),
                        "observaciones": observacion.strip(),
                    }

                    if respuesta in ("Sí", "No"):
                        respondidos += 1
                    if respuesta == "Sí":
                        cumplen += 1
                    elif respuesta == "No":
                        pendientes += 1

                    st.divider()

            porcentaje = round((respondidos / TOTAL_REQUISITOS) * 100)
            st.markdown(
                f"**Avance de captura: {respondidos}/{TOTAL_REQUISITOS} "
                f"({porcentaje}%)**"
            )
            st.caption(
                f"Cumplen: {cumplen} | Pendientes (NO): {pendientes} | "
                f"Sin revisar: {TOTAL_REQUISITOS - respondidos}"
            )

            guardar = st.form_submit_button(
                "💾 Guardar checklist",
                use_container_width=True
            )

        if guardar:
            # Leer las respuestas actuales del estado para guardar el formulario.
            respuestas_guardadas = {}
            for categoria, requisitos in CHECKLIST.items():
                for indice, requisito in enumerate(requisitos):
                    nombre = requisito["nombre"]
                    respuesta = st.session_state.get(
                        crear_clave(categoria, indice), "Sin revisar"
                    )
                    fecha = st.session_state.get(
                        f"fecha_{serie_id}_{categoria}_{indice}"
                    )
                    observacion = st.session_state.get(
                        f"obs_{serie_id}_{categoria}_{indice}", ""
                    )
                    respuestas_guardadas[nombre] = {
                        "categoria": categoria,
                        "respuesta": respuesta,
                        "fecha": fecha.isoformat() if fecha else "",
                        "campo_fecha": requisito.get("fecha", ""),
                        "observaciones": observacion.strip(),
                    }

            registro = construir_registro(unidad, respuestas_guardadas)
            st.session_state.checklists_guardados.append(registro)
            st.success(
                "Checklist guardado en esta sesión. "
                "Puedes descargar el historial en Excel."
            )
            st.rerun()

# =====================================
# HISTORIAL DE LA SESIÓN Y EXPORTACIÓN
# =====================================

st.divider()
st.subheader("📚 Historial de checklists de esta sesión")

historial = st.session_state.checklists_guardados

if not historial:
    st.info("Todavía no hay checklists guardados en esta sesión.")
else:
    resumen = []
    detalle = []

    for registro in historial:
        respuestas = registro["respuestas"]
        total_si = sum(1 for r in respuestas.values() if r["respuesta"] == "Sí")
        total_no = sum(1 for r in respuestas.values() if r["respuesta"] == "No")
        total_sin = sum(
            1 for r in respuestas.values()
            if r["respuesta"] == "Sin revisar"
        )
        resumen.append({
            "Fecha de revisión": registro["fecha_revision"],
            "Serie": registro["serie"],
            "Placa": registro["placa"],
            "Línea": registro["linea"],
            "Modelo": registro["modelo"],
            "Cliente": registro["cliente"],
            "Sí": total_si,
            "No / Pendientes": total_no,
            "Sin revisar": total_sin,
        })

        for nombre, respuesta in respuestas.items():
            detalle.append({
                "Fecha de revisión": registro["fecha_revision"],
                "Serie": registro["serie"],
                "Placa": registro["placa"],
                "Categoría": respuesta["categoria"],
                "Requisito": nombre,
                "Resultado": respuesta["respuesta"],
                "Campo de fecha": respuesta["campo_fecha"],
                "Fecha capturada": respuesta["fecha"],
                "Observaciones": respuesta["observaciones"],
            })

    df_resumen = pd.DataFrame(resumen)
    df_detalle = pd.DataFrame(detalle)

    st.dataframe(df_resumen, use_container_width=True, hide_index=True)

    salida = BytesIO()
    with pd.ExcelWriter(salida, engine="openpyxl") as writer:
        df_resumen.to_excel(writer, sheet_name="Resumen", index=False)
        df_detalle.to_excel(writer, sheet_name="Detalle", index=False)

    st.download_button(
        "📥 Descargar historial en Excel",
        data=salida.getvalue(),
        file_name="Casanova_Checklists.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    st.warning(
        "Importante: por ahora los registros se conservan durante la sesión "
        "activa de Streamlit. Para conservarlos permanentemente entre sesiones "
        "y usuarios, el siguiente paso es conectar una base de datos como "
        "Supabase o PostgreSQL."
    )
