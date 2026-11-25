import uuid
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
import requests
import re
import unicodedata

from io import BytesIO
from datetime import date, datetime
from supabase import create_client

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

ESTADOS_PERMITIDOS = [
    "Confirmación de servicio",
    "Orden de Servicio Cerrada por el Cliente",
    "Solicitud en Aprobación",
    "Carga de documentos",
    "Validación de documentos",
    "Orden de Servicio Finalizada",
    "Orden de Servicio en Proceso"
]

# =====================================
# ESTILOS
# =====================================

st.markdown("""
<style>
.stApp {
    font-family: "Montserrat", "Century Gothic", Arial, sans-serif;
    background-color: #EEF2F8;
    color: #213769;
}
h1, h2, h3, h4, label {
    font-family: "Montserrat", "Century Gothic", Arial, sans-serif;
    color: #213769 !important;
}
div[data-testid="stMetric"] {
    background: white;
    border: 1px solid #D2DCEB;
    padding: 8px 12px;
    border-radius: 10px;
}
div[data-testid="stMetricValue"] {
    font-weight: 700;
    font-size: 1.35rem;
    color: #213769;
}
div.stButton > button,
div.stDownloadButton > button,
button[kind="primary"] {
    background-color: #004876 !important;
    color: white !important;
    border-radius: 8px;
}
[data-testid="stSidebar"] { background-color: #EEF2F8; }
[data-testid="stMetric"] { border-top: 4px solid #FFB700 !important; }
</style>
""", unsafe_allow_html=True)

# =====================================
# SUPABASE
# =====================================

try:
    if "supabase" not in st.session_state:
        st.session_state.supabase = create_client(
            st.secrets["SUPABASE_URL"],
            st.secrets["SUPABASE_KEY"]
        )

    db = st.session_state.supabase

except Exception:
    st.error("No fue posible configurar Supabase. Revisa Secrets.")
    st.stop()

# =====================================
# FUNCIONES
# =====================================

def cliente_privado():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_KEY"])


def administrador_privado():
    identidad = db.auth.get_user().user
    if not identidad or identidad.id != st.session_state.get("usuario_id"):
        raise PermissionError("Sesión inválida")
    privado = cliente_privado()
    filas = privado.table("perfiles").select("rol,activo").eq("id", identidad.id).execute().data
    if not filas or not filas[0]["activo"] or filas[0]["rol"] != "maestro":
        raise PermissionError("Acceso denegado")
    return privado


def normalizar_serie(valor):
    if pd.isna(valor):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(valor).upper())


def normalizar_texto(valor):
    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        c for c in texto
        if not unicodedata.combining(c)
    )
    return " ".join(texto.split())


def interpretar_fecha(valor):
    if pd.isna(valor) or not str(valor).strip():
        return None
    texto = str(valor).strip()
    # Excel puede entregar fechas como objetos o texto ISO.
    if re.match(r"^\d{4}-\d{2}-\d{2}", texto):
        fecha = pd.to_datetime(texto, errors="coerce", yearfirst=True)
    else:
        fecha = pd.to_datetime(texto, errors="coerce", dayfirst=True)
    if pd.isna(fecha):
        return None
    if fecha.tzinfo is not None:
        fecha = fecha.tz_convert("America/Mexico_City").tz_localize(None)
    return fecha.isoformat()


def mostrar(valor):
    if pd.isna(valor):
        return "Sin información"

    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")

    texto = str(valor).strip()

    if texto.lower() in ("", "nan", "none"):
        return "Sin información"

    return texto


def consultar_tabla(tabla):
    registros = []
    inicio = 0
    limite = 500

    while True:
        respuesta = (
            db.table(tabla)
            .select("*")
            .order("id")
            .range(inicio, inicio + limite - 1)
            .execute()
        )

        bloque = respuesta.data or []
        registros.extend(bloque)

        if len(bloque) < limite:
            break

        inicio += limite

    return registros


@st.cache_data(show_spinner="Descargando base maestra...")
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

    faltantes = [
        c for c in COLUMNAS
        if c not in df.columns
    ]

    if faltantes:
        raise ValueError(
            "Columnas faltantes: " + ", ".join(faltantes)
        )

    for campo in ["Marca", "Estatus", "Subestatus"]:
        coincidencia = next((c for c in df.columns if normalizar_texto(c) == normalizar_texto(campo)), None)
        df[campo] = df[coincidencia] if coincidencia else "Sin información"
    df = df[COLUMNAS + ["Marca", "Estatus", "Subestatus"]].copy()

    df["Serie"] = df["Serie"].apply(normalizar_serie)

    df["Nombre Cliente"] = (
        df["Nombre Cliente"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    df.loc[
        df["Nombre Cliente"].str.upper().isin([
            "",
            "SIN INFORMACION",
            "SIN INFORMACIÓN",
            "NAN",
            "NONE"
        ]),
        "Nombre Cliente"
    ] = "SIN CONTRATO"

    df.attrs["actualizada"] = datetime.now().astimezone().isoformat()
    return df


def estado_respuesta(r):
    if r is None:
        return "SIN REGISTRO"
    if r.get("no_aplica"):
        return "NO APLICA"
    if r.get("respuesta") is True:
        return "SÍ"
    if r.get("respuesta") is False:
        return "NO"
    return "SIN REVISAR"


def construir_concentrado(df, respuestas, requisitos):
    columnas = {
        "id": "ID revisión", "serie": "Serie", "placa": "Placa",
        "linea": "Línea", "modelo": "Modelo", "unidad_negocio": "Unidad de negocio",
        "nombre_cliente": "Nombre cliente", "almacen": "Almacén",
        "usuario": "Usuario", "Sucursal": "Sucursal",
        "Fecha de revisión": "Fecha de revisión", "estatus": "Estatus",
        "observaciones": "Observaciones"
    }
    base = df[list(columnas)].copy().rename(columns=columnas)
    detalle = {(r["revision_id"], r["requisito_id"]): r for r in respuestas}
    usados = {r["requisito_id"] for r in respuestas}
    for req in sorted(requisitos, key=lambda r: (r.get("orden") or 0, r["id"])):
        if not req.get("activo") and req["id"] not in usados:
            continue
        nombre = req["requisito"].upper()
        if nombre in base.columns:
            nombre += f" ({req['id']})"
        filas = [detalle.get((i, req["id"])) for i in base["ID revisión"]]
        base[nombre] = [estado_respuesta(r) for r in filas]
        if req.get("requiere_fecha") or any(r and r.get("fecha_vencimiento") for r in filas):
            campo = (req.get("nombre_campo_fecha") or f"FECHA {nombre}").upper()
            if campo in base.columns:
                campo += f" ({req['id']})"
            base[campo] = pd.to_datetime([r.get("fecha_vencimiento") if r else None for r in filas], errors="coerce")
    return base


def excel_concentrado(df):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    salida = BytesIO()
    with pd.ExcelWriter(salida, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Concentrado", index=False)
        ws = writer.sheets["Concentrado"]
        ws.freeze_panes = "D2"
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 32
        for j, col in enumerate(df.columns, 1):
            celda = ws.cell(1, j)
            celda.fill = PatternFill("solid", fgColor="213769")
            celda.font = Font(bold=True, color="FFFFFF")
            celda.alignment = Alignment(wrap_text=True, vertical="center")
            ancho = max([len(str(col))] + [len(str(v)) for v in df[col].dropna().head(1000)])
            ws.column_dimensions[get_column_letter(j)].width = min(45, max(14, ancho + 3))
            for fila in range(2, ws.max_row + 1):
                c = ws.cell(fila, j)
                if isinstance(c.value, datetime):
                    c.number_format = "dd/mm/yyyy hh:mm" if col == "Fecha de revisión" else "dd/mm/yyyy"
                elif isinstance(c.value, str):
                    c.data_type = "s"
                    colores = {"SÍ": ("EEF2F8", "004876"), "NO": ("FFB700", "213769"), "SIN REVISAR": ("EEF2F8", "213769"), "NO APLICA": ("EEF2F8", "213769"), "SIN REGISTRO": ("EEF2F8", "213769")}
                    if c.value in colores:
                        fondo, letra = colores[c.value]
                        c.fill = PatternFill("solid", fgColor=fondo)
                        c.font = Font(color=letra)
    return salida.getvalue()


def descargar_excel(tablas, nombre):

    salida = BytesIO()

    with pd.ExcelWriter(
        salida,
        engine="openpyxl"
    ) as writer:

        for hoja, datos in tablas.items():
            datos.to_excel(
                writer,
                sheet_name=hoja,
                index=False
            )

    st.download_button(
        "📥 Descargar Excel",
        data=salida.getvalue(),
        file_name=nombre,
        mime=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        )
    )


# =====================================
# ENCABEZADO
# =====================================

st.title("🚗 CASANOVA CHECKLIST")

st.caption(
    "CORPORATIVO | CONTROL DE TRÁMITES VEHICULARES"
)

st.divider()

# =====================================
# INICIO DE SESIÓN
# =====================================

if "usuario_id" not in st.session_state:

    st.subheader("🔐 Iniciar sesión")

    with st.form("login"):

        correo = st.text_input("Usuario o correo electrónico")

        password = st.text_input(
            "Contraseña",
            type="password"
        )

        entrar = st.form_submit_button(
            "Iniciar sesión"
        )

    if entrar:

        try:
            identificador = correo.strip().lower()
            if "@" not in identificador:
                privado = cliente_privado()
                filas = privado.table("perfiles").select("id,activo").eq("usuario", identificador).execute().data
                if not filas or not filas[0]["activo"]:
                    raise ValueError("Acceso inválido")
                identificador = privado.auth.admin.get_user_by_id(filas[0]["id"]).user.email
            resultado = db.auth.sign_in_with_password({
                "email": identificador,
                "password": password
            })

            st.session_state.usuario_id = (
                resultado.user.id
            )

            st.rerun()

        except Exception:
            st.error("Usuario o contraseña incorrectos.")

    st.stop()

# =====================================
# PERFIL Y PERMISOS
# =====================================

try:

    perfiles = (
        db.table("perfiles")
        .select("*")
        .eq("id", st.session_state.usuario_id)
        .execute()
        .data
    )

    if not perfiles or not perfiles[0]["activo"]:
        st.error("Tu usuario no tiene acceso activo.")

        if st.button("Volver al inicio"):
            st.session_state.clear()
            st.rerun()

        st.stop()

    perfil = perfiles[0]

except Exception:
    st.error("No fue posible consultar tu perfil.")

    if st.button("Iniciar sesión nuevamente"):
        st.session_state.clear()
        st.rerun()

    st.stop()

rol_actual = perfil["rol"]
es_maestro = rol_actual == "maestro"
es_admin = rol_actual in ("maestro", "administrador")
consulta_general = es_admin or rol_actual == "administracion_flota"
puede_capturar = es_admin or rol_actual == "capturista"
ROLES = ["capturista", "administrador", "administracion_flota", "maestro"]
ETIQUETAS = {"capturista": "Capturista", "administrador": "Administrador operativo", "administracion_flota": "Administración de Flota", "maestro": "Maestro"}

usuario_id = perfil["id"]
nombre_usuario = perfil["nombre"]

# =====================================
# SUCURSALES
# =====================================

try:

    sucursales = (
        db.table("sucursales")
        .select("*")
        .eq("activa", True)
        .execute()
        .data
    )

except Exception:
    st.error("No fue posible consultar las sucursales.")
    st.stop()

mapa_sucursales = {
    s["id"]: s["nombre"]
    for s in sucursales
}

# =====================================
# MENÚ
# =====================================

st.sidebar.title("CASANOVA")

st.sidebar.write(f"👤 {nombre_usuario}")

st.sidebar.caption(ETIQUETAS.get(rol_actual, rol_actual))
opciones = (["Capturar checklist"] if puede_capturar else []) + ["Historial", "Mi contraseña", "Dashboard"]
if consulta_general:
    opciones.append("Carga de ASIG")
if es_maestro:
    opciones.append("Administración")

if st.sidebar.button("🔄 Actualizar base maestra"):
    try:
        cargar_base.clear()
        cargar_base()
        st.sidebar.success("Base actualizada")
    except Exception:
        st.sidebar.error("No se pudo actualizar la base.")

modulo = st.sidebar.radio(
    "Menú principal",
    opciones
)

if st.sidebar.button("Cerrar sesión"):

    try:
        db.auth.sign_out()
    finally:
        st.session_state.clear()

    st.rerun()

# =====================================
# CAPTURA DE CHECKLIST
# =====================================

if modulo == "Capturar checklist" and puede_capturar:

    st.subheader("🔎 Consulta de vehículos")

    if not mapa_sucursales:
        st.warning("No tienes una sucursal asignada.")
        st.stop()

    sucursal_id = st.selectbox(
        "Sucursal de captura",
        list(mapa_sucursales.keys()),
        format_func=lambda x: mapa_sucursales[x]
    )


    try:
        df = cargar_base()

        st.caption(f"Base conectada | {len(df):,} vehículos | Actualizada: {pd.Timestamp(df.attrs['actualizada']).tz_convert('America/Mexico_City').strftime('%d/%m/%Y %H:%M')}")

    except Exception:
        st.error("No fue posible consultar la API maestra.")
        st.stop()

    busqueda = st.text_input(
        "Últimos 9 caracteres de la serie",
        max_chars=9
    )

    if busqueda:

        busqueda = normalizar_serie(busqueda)

        if len(busqueda) != 9:
            st.warning("Ingresa exactamente 9 caracteres.")
            st.stop()

        resultados = df[
            df["Serie"].str.endswith(busqueda)
        ]

        if resultados.empty:
            st.error("No encontramos la unidad.")
            st.stop()

        seleccion = st.selectbox(
            "Vehículo encontrado",
            resultados.index.tolist(),
            format_func=lambda i: (
                f"{resultados.loc[i, 'Serie']} | "
                f"{resultados.loc[i, 'Linea']} | "
                f"{resultados.loc[i, 'Placa']}"
            )
        )

        unidad = resultados.loc[seleccion]
        serie = unidad["Serie"]

        st.divider()
        st.subheader("📋 Información del vehículo")

        c1, c2, c3 = st.columns(3)

        c1.metric("Línea", mostrar(unidad["Linea"]))
        c2.metric("Marca", mostrar(unidad["Marca"]))
        c3.metric("Modelo", mostrar(unidad["Modelo"]))

        c1, c2, c3 = st.columns(3)

        c1.metric("Placa", mostrar(unidad["Placa"]))

        c2.metric(
            "Unidad de negocio",
            mostrar(unidad["Unidad de Negocio"])
        )

        c3.metric(
            "Cliente",
            mostrar(unidad["Nombre Cliente"])
        )

        st.write("**Serie completa:**", serie)

        st.write(
            "**Estatus:**", mostrar(unidad["Estatus"])
        )

        st.write("**Subestatus:**", mostrar(unidad["Subestatus"]))
        st.write(
            "**Almacén:**",
            mostrar(unidad["Almacen"])
        )

        # =============================
        # FOLIOS ASIG
        # =============================

        st.divider()
        st.subheader("📂 Folios ASIG")

        try:

            folios = []
            inicio = 0
            while True:
                bloque = (
                    db.table("atenciones_vehiculo")
                    .select("folio,conceptos,estado_atencion,fecha_creacion")
                    .eq("serie", serie)
                    .order("id")
                    .range(inicio, inicio + 499)
                    .execute().data or []
                )
                folios.extend(bloque)
                if len(bloque) < 500:
                    break
                inicio += 500

            permitidos = {normalizar_texto(e) for e in ESTADOS_PERMITIDOS}
            folios = [f for f in folios if normalizar_texto(
                f["estado_atencion"]) in permitidos]

            if folios:
                tabla = pd.DataFrame(folios)
                fechas = pd.to_datetime(
                    tabla["fecha_creacion"], format="mixed", errors="coerce"
                )
                hoy = pd.Timestamp.now(tz="America/Mexico_City").tz_localize(None).normalize()
                tabla["dias"] = (hoy - fechas.dt.normalize()).dt.days.astype("Int64")
                tabla["conceptos"] = tabla["conceptos"].apply(mostrar)
                tabla["fecha_creacion"] = fechas.dt.strftime("%d/%m/%Y %H:%M").fillna("Sin información")
                tabla = tabla.sort_values("dias", ascending=False, na_position="last")
                tabla = tabla.rename(columns={
                    "folio": "Folio",
                    "conceptos": "Conceptos",
                    "estado_atencion": "Estado de atención",
                    "fecha_creacion": "Fecha de creación",
                    "dias": "Días desde creación"
                })
                st.metric("Folios ASIG", len(tabla))
                st.dataframe(tabla[["Folio", "Conceptos", "Estado de atención",
                    "Fecha de creación", "Días desde creación"]],
                    hide_index=True, use_container_width=True)
            else:
                st.info("Sin folios ASIG visibles.")

        except Exception:
            st.warning("No fue posible consultar los folios.")

        # =============================
        # CHECKLIST DINÁMICO
        # =============================

        st.divider()
        st.subheader("📝 Checklist documental")

        try:

            requisitos = (
                db.table("checklist_requisitos")
                .select("*")
                .eq("activo", True)
                .order("orden")
                .execute()
                .data
            )

        except Exception:
            st.error("No fue posible cargar el checklist.")
            st.stop()

        if not requisitos:
            st.warning("No existen requisitos activos.")
            st.stop()

        ultima = db.table("checklist_revisiones").select("id,fecha_revision").eq("serie", serie).order("fecha_revision", desc=True).order("id", desc=True).limit(1).execute().data
        previas = {}
        if ultima:
            previas = {r["requisito_id"]: r for r in db.table("checklist_respuestas").select("*").eq("revision_id", ultima[0]["id"]).execute().data}
            st.caption("Respuestas de la última revisión accesible. Confirma que siguen vigentes antes de guardar.")
        respuestas = []

        with st.form(f"checklist_{serie}_{sucursal_id}"):

            categoria_anterior = None

            for r in requisitos:

                if r["categoria"] != categoria_anterior:

                    st.markdown(
                        f"### {r['categoria'].upper()}"
                    )

                    categoria_anterior = r["categoria"]

                clave = f"{serie}_{sucursal_id}_{r['id']}_{ultima[0]['id'] if ultima else 0}"
                previa = previas.get(r["id"], {})
                indice = {"SÍ": 0, "NO": 1, "NO APLICA": 2}.get(estado_respuesta(previa))

                respuesta = st.radio(
                    r["requisito"].upper(),
                    ["Sí", "No", "No aplica"],
                    index=indice,
                    horizontal=True,
                    key=f"respuesta_{clave}"
                )

                fecha = None

                if r["requiere_fecha"]:

                    fecha = st.date_input(
                        r["nombre_campo_fecha"] or "Fecha",
                        value=date.fromisoformat(previa["fecha_vencimiento"]) if previa.get("fecha_vencimiento") else None,
                        format="DD/MM/YYYY",
                        min_value=date(1990, 1, 1),
                        max_value=date(2100, 12, 31),
                        key=f"fecha_{clave}"
                    )

                observacion = st.text_input(
                    "Observaciones (opcional)",
                    value=previa.get("observaciones") or "",
                    key=f"obs_{clave}"
                )

                respuestas.append({
                    "requisito_id": r["id"],
                    "respuesta": {
                        "Sí": True,
                        "No": False,
                        "No aplica": None,
                        None: None
                    }[respuesta],
                    "no_aplica": respuesta == "No aplica",
                    "fecha_vencimiento": (
                        fecha.isoformat()
                        if fecha and respuesta == "Sí" else None
                    ),
                    "observaciones": observacion
                })

                st.divider()

            observaciones_generales = st.text_area(
                "Observaciones generales"
            )

            guardar = st.form_submit_button(
                "💾 Guardar checklist"
            )

        if guardar:

            sin_revisar = sum(
                r["respuesta"] is None and not r["no_aplica"]
                for r in respuestas
            )

            pendientes = sum(
                r["respuesta"] is False
                for r in respuestas
            )

            if sin_revisar:
                st.warning("Responde todos los requisitos antes de guardar.")
                st.stop()
            elif pendientes:
                estatus = "Con pendientes"
            else:
                estatus = "No aplica" if all(r["no_aplica"] for r in respuestas) else "Completo"

            revision = {
                "serie": serie,
                "placa": mostrar(unidad["Placa"]),
                "linea": mostrar(unidad["Linea"]),
                "version": mostrar(unidad["Version"]),
                "modelo": mostrar(unidad["Modelo"]),
                "unidad_negocio": mostrar(
                    unidad["Unidad de Negocio"]
                ),
                "nombre_cliente": mostrar(
                    unidad["Nombre Cliente"]
                ),
                "almacen": mostrar(unidad["Almacen"]),
                "usuario": nombre_usuario,
                "usuario_id": usuario_id,
                "sucursal_id": sucursal_id,
                "estatus": estatus,
                "observaciones": observaciones_generales
            }

            try:
                resultado = db.rpc("guardar_checklist_atomico", {"p_revision": revision, "p_respuestas": respuestas}).execute()
                st.success(f"Checklist guardado correctamente. Registro: {resultado.data}")
            except Exception:
                st.error("No se confirmó el guardado. Revisa el historial antes de reintentar.")

# =====================================
# HISTORIAL
# =====================================

elif modulo == "Historial":

    st.subheader("📚 Historial de checklists")

    try:
        revisiones = consultar_tabla("checklist_revisiones")
        respuestas = consultar_tabla("checklist_respuestas")
        requisitos = consultar_tabla("checklist_requisitos")
        df = pd.DataFrame(revisiones)

        if df.empty:
            st.info("No hay registros disponibles.")
        else:
            df["Sucursal"] = df["sucursal_id"].map(mapa_sucursales).fillna("Sin información")
            df["Fecha de revisión"] = pd.to_datetime(df["fecha_revision"], utc=True, errors="coerce", format="mixed").dt.tz_convert("America/Mexico_City").dt.tz_localize(None)
            df = df.sort_values("Fecha de revisión", ascending=False)
            c1, c2, c3 = st.columns(3)
            c1.metric("Revisiones", len(df))
            c2.metric("Completas", int(df["estatus"].eq("Completo").sum()))
            c3.metric("No completas", int(df["estatus"].ne("Completo").sum()))
            a, b, c = st.columns(3)
            texto = a.text_input("Serie o placa")
            suc = b.selectbox("Sucursal", ["Todas"] + sorted(df["Sucursal"].unique().tolist()))
            capt = c.selectbox("Capturista", ["Todos"] + sorted(df["usuario"].dropna().unique().tolist()))
            a, b, c = st.columns(3)
            estado = a.selectbox("Estatus", ["Todos"] + sorted(df["estatus"].dropna().unique().tolist()))
            desde = b.date_input("Fecha inicial", value=None, format="DD/MM/YYYY")
            hasta = c.date_input("Fecha final", value=None, format="DD/MM/YYYY")
            if desde and hasta and desde > hasta:
                st.warning("La fecha inicial debe ser anterior o igual a la final.")
                st.stop()
            if texto.strip():
                t = texto.strip()
                df = df[df["serie"].str.contains(t, case=False, regex=False, na=False) | df["placa"].str.contains(t, case=False, regex=False, na=False)]
            if suc != "Todas":
                df = df[df["Sucursal"].eq(suc)]
            if capt != "Todos":
                df = df[df["usuario"].eq(capt)]
            if estado != "Todos":
                df = df[df["estatus"].eq(estado)]
            if desde:
                df = df[df["Fecha de revisión"] >= pd.Timestamp(desde)]
            if hasta:
                df = df[df["Fecha de revisión"] < pd.Timestamp(hasta) + pd.Timedelta(days=1)]
            concentrado = construir_concentrado(df, respuestas, requisitos)
            st.caption(f"{len(concentrado):,} revisiones encontradas")
            st.dataframe(concentrado, hide_index=True, use_container_width=True,
                         column_config={col: st.column_config.DatetimeColumn(format="DD/MM/YYYY HH:mm" if col == "Fecha de revisión" else "DD/MM/YYYY") for col in concentrado.columns if pd.api.types.is_datetime64_any_dtype(concentrado[col])})
            if not concentrado.empty:
                st.download_button("📥 Descargar concentrado Excel", data=excel_concentrado(concentrado), file_name="Casanova_Checklists.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception:
        st.error("No fue posible consultar el historial.")

# =====================================
# DASHBOARD
# =====================================

elif modulo == "Dashboard":
    st.subheader("Resumen ejecutivo | Control documental")
    colores = {"SÍ": "#004876", "NO": "#FFB700", "NO APLICA": "#D2DCEB",
               "SIN REVISAR": "#8493AD", "SIN REGISTRO": "#8493AD",
               "Completo": "#004876", "Con pendientes": "#FFB700",
               "Histórico incompleto": "#8493AD", "No aplica": "#D2DCEB"}
    try:
        df = pd.DataFrame(consultar_tabla("checklist_revisiones"))
        respuestas = consultar_tabla("checklist_respuestas")
        requisitos = consultar_tabla("checklist_requisitos")
        activos = sorted([r for r in requisitos if r.get("activo")], key=lambda r: (r.get("orden") or 0, r["id"]))
        if df.empty or not activos:
            st.info("No hay revisiones o requisitos activos disponibles.")
            st.stop()
        df["Sucursal"] = df["sucursal_id"].map(mapa_sucursales).fillna("Sin información")
        df["Fecha de revisión"] = pd.to_datetime(df["fecha_revision"], utc=True, errors="coerce", format="mixed").dt.tz_convert("America/Mexico_City").dt.tz_localize(None)
        a,b,c = st.columns(3)
        suc = a.selectbox("Sucursal", ["Todas"] + sorted(df["Sucursal"].unique()))
        desde = b.date_input("Desde", value=None, format="DD/MM/YYYY")
        hasta = c.date_input("Hasta", value=None, format="DD/MM/YYYY")
        if desde and hasta and desde > hasta:
            st.warning("Revisa el periodo seleccionado.")
            st.stop()
        ids_vigentes = set()
        offset = 0
        while True:
            bloque = db.rpc("revisiones_vigentes_autorizadas").order("id").range(offset, offset+499).execute().data
            ids_vigentes.update(r["id"] for r in bloque)
            if len(bloque) < 500: break
            offset += 500
        historial_visible = df.copy()
        df = df[df["id"].isin(ids_vigentes)]
        if suc != "Todas": df = df[df["Sucursal"] == suc]
        if desde: df = df[df["Fecha de revisión"] >= pd.Timestamp(desde)]
        if hasta: df = df[df["Fecha de revisión"] < pd.Timestamp(hasta) + pd.Timedelta(days=1)]
        if df.empty:
            st.info("No hay revisiones para estos filtros.")
            st.stop()
        ult = df.sort_values(["Fecha de revisión", "id"], na_position="first").drop_duplicates("serie", keep="last").copy()
        lookup = {(r["revision_id"], r["requisito_id"]): r for r in respuestas}
        nombres = {r["id"]: r["requisito"] for r in activos}
        largo = pd.DataFrame([{"id": i, "Sucursal": sucursal, "Requisito": nombres[r["id"]], "Respuesta": estado_respuesta(lookup.get((i,r["id"])))} for i,sucursal in zip(ult["id"],ult["Sucursal"]) for r in activos])
        def clasificar(g):
            estados = set(g["Respuesta"])
            if "NO" in estados: return "Con pendientes"
            if estados & {"SIN REVISAR", "SIN REGISTRO"}: return "Histórico incompleto"
            if estados == {"NO APLICA"}: return "No aplica"
            return "Completo"
        ult["Resultado"] = ult["id"].map({i: clasificar(g) for i,g in largo.groupby("id")})
        n = len(ult); completos = int(ult["Resultado"].eq("Completo").sum()); pendientes = int(ult["Resultado"].eq("Con pendientes").sum())
        aplicables = n - int(ult["Resultado"].eq("No aplica").sum())
        a,b,c,d = st.columns(4)
        a.metric("Unidades revisadas", f"{n:,}")
        b.metric("Cumplimiento general", f"{completos/aplicables:.1%}" if aplicables else "N/A")
        c.metric("Unidades completas", f"{completos:,}")
        d.metric("Con pendientes (NO)", f"{pendientes:,}")
        st.caption("Última revisión global por serie, después filtrada por sucursal y fecha. Los históricos incompletos no cuentan como completos; las unidades totalmente no aplicables se excluyen del porcentaje.")
        def aplicar_seleccion(tipo=None, valores=()):
            st.session_state["dash_doc"] = "Todos"
            st.session_state["dash_resp"] = "Todas"
            st.session_state["dash_resultado"] = "Todas"
            if tipo:
                st.session_state["dash_filtro"] = (tipo, tuple(valores))
            else:
                st.session_state.pop("dash_filtro", None)
            st.session_state["dash_reset"] = st.session_state.get("dash_reset", 0) + 1
        st.markdown("### Detalle de unidades")
        st.button("Limpiar selección de gráfica", on_click=aplicar_seleccion)
        filtro=st.session_state.get("dash_filtro")
        detalle=ult.copy()
        if filtro:
            tipo, valores=filtro
            if tipo=="documento":
                ids=largo.loc[(largo["Requisito"]==valores[0]) & (largo["Respuesta"]==valores[1]),"id"]
                detalle=detalle[detalle["id"].isin(ids)]
            elif tipo=="general":
                detalle=detalle[detalle["Resultado"]==valores[0]]
            else:
                detalle=detalle[(detalle["Sucursal"]==valores[0]) & (detalle["Resultado"]==valores[1])]
            st.caption("Selección: " + " · ".join(valores))
        a,b,c=st.columns(3)
        doc=a.selectbox("Documento",["Todos"]+list(nombres.values()),key="dash_doc")
        resp=b.selectbox("Respuesta",["Todas","SÍ","NO","NO APLICA","SIN REVISAR","SIN REGISTRO"],key="dash_resp")
        resultado=c.selectbox("Situación general",["Todas","Completo","Con pendientes","Histórico incompleto","No aplica"],key="dash_resultado")
        if doc!="Todos" or resp!="Todas":
            g=largo
            if doc!="Todos": g=g[g["Requisito"]==doc]
            if resp!="Todas": g=g[g["Respuesta"]==resp]
            detalle=detalle[detalle["id"].isin(g["id"])]
        if resultado!="Todas": detalle=detalle[detalle["Resultado"]==resultado]
        st.metric("Unidades seleccionadas",len(detalle))
        concentrado=construir_concentrado(detalle,respuestas,requisitos)
        concentrado["Situación actual"] = detalle["Resultado"].to_numpy()
        st.dataframe(concentrado,hide_index=True,use_container_width=True)
        if not concentrado.empty:
            st.download_button("Descargar detalle Excel",excel_concentrado(concentrado),"Dashboard_Casanova.xlsx",mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        pendientes_excel = []
        hoy = pd.Timestamp.now(tz="America/Mexico_City").tz_localize(None).normalize()
        for _, unidad in detalle.iterrows():
            historial = historial_visible[historial_visible["serie"] == unidad["serie"]].sort_values(["Fecha de revisión", "id"], ascending=False)
            for req in activos:
                if estado_respuesta(lookup.get((unidad["id"], req["id"]))) != "NO":
                    continue
                inicio = unidad["Fecha de revisión"]
                for _, anterior in historial.iterrows():
                    if estado_respuesta(lookup.get((anterior["id"], req["id"]))) != "NO":
                        break
                    inicio = anterior["Fecha de revisión"]
                pendientes_excel.append({"Serie": unidad["serie"], "Placa": unidad["placa"], "Línea": unidad["linea"], "Modelo": unidad["modelo"], "Cliente": unidad["nombre_cliente"], "Unidad de negocio": unidad["unidad_negocio"], "Almacén": unidad["almacen"], "Sucursal": unidad["Sucursal"], "Responsable": unidad["usuario"], "Fecha de revisión": unidad["Fecha de revisión"], "Pendiente": req["requisito"], "Detectado desde (historial visible)": inicio, "Días de pendiente": (hoy-inicio.normalize()).days if pd.notna(inicio) else None})
        if pendientes_excel:
            st.download_button("Descargar pendientes Excel", excel_concentrado(pd.DataFrame(pendientes_excel)), "Pendientes_Casanova.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        st.divider()
        def estilo(fig, altura=290):
            fig.update_layout(height=altura, margin=dict(l=15,r=15,t=35,b=15), font=dict(color="#213769", family="Montserrat, Century Gothic, Arial, sans-serif"), paper_bgcolor="white", plot_bgcolor="white", legend_title_text="")
            return fig
        def seleccion(fig, key, destino):
            def al_seleccionar():
                evento = st.session_state.get(key, {})
                puntos = evento.get("selection", {}).get("points", [])
                if puntos:
                    datos = puntos[-1].get("customdata")
                    if datos is not None and len(datos):
                        aplicar_seleccion(destino, datos)
            return st.plotly_chart(estilo(fig), theme=None, use_container_width=True,
                                   key=key, on_select=al_seleccionar, selection_mode="points")
        a,b = st.columns(2)
        with a:
            st.markdown("**Situación documental**")
            conteo = ult["Resultado"].value_counts().rename_axis("Resultado").reset_index(name="Unidades")
            fig = px.pie(conteo, names="Resultado", values="Unidades", hole=.68, color="Resultado", color_discrete_map=colores)
            fig.update_traces(textinfo="value+percent", textposition="outside", outsidetextfont=dict(color="#213769"), marker=dict(line=dict(color="#FFFFFF", width=2)))
            fig.add_annotation(text=f"<b>{n:,}</b>", x=.5,y=.5,showarrow=False,font_size=30)
            st.plotly_chart(estilo(fig), theme=None, use_container_width=True)
            for estado, cantidad in zip(conteo["Resultado"], conteo["Unidades"]):
                st.button(f"{estado}: {cantidad}", key=f"general_{estado}",
                          on_click=aplicar_seleccion, args=("general", (estado,)))
        with b:
            st.markdown("**Avance acumulado de unidades**")
            primera = df.dropna(subset=["Fecha de revisión"]).sort_values("Fecha de revisión").drop_duplicates("serie")
            avance = primera.groupby(primera["Fecha de revisión"].dt.normalize()).size().cumsum().rename("Unidades").reset_index()
            fig = px.area(avance, x="Fecha de revisión", y="Unidades", markers=True, color_discrete_sequence=["#004876"])
            fig.update_traces(hovertemplate="%{x|%d/%m/%Y}: %{y} unidades")
            st.plotly_chart(estilo(fig), theme=None, use_container_width=True)
        st.markdown("### Cumplimiento por documento")
        resumen_doc = largo.groupby(["Requisito", "Respuesta"]).size().reset_index(name="Unidades")
        fig = px.bar(resumen_doc, y="Requisito", x="Unidades", color="Respuesta", orientation="h", color_discrete_map=colores, custom_data=["Requisito", "Respuesta"], text="Unidades")
        fig.update_layout(barmode="stack", yaxis_title="", xaxis_title="Unidades")
        seleccion(fig, f"dash_docs_{st.session_state.get('dash_reset',0)}", "documento")
        st.markdown("### Comparativo por sucursal")
        resumen=ult.groupby(["Sucursal","Resultado"]).size().reset_index(name="Unidades")
        fig=px.bar(resumen,y="Sucursal",x="Unidades",orientation="h",color="Resultado",color_discrete_map=colores,text="Unidades",custom_data=["Sucursal","Resultado"])
        fig.update_traces(textposition="outside", cliponaxis=False)
        seleccion(fig,f"dash_barras_{st.session_state.get('dash_reset',0)}","sucursal")
        with st.expander("Consultar detalle por sucursal"):
            for fila in resumen.itertuples(index=False):
                st.button(f"{fila.Sucursal} · {fila.Resultado}: {fila.Unidades}",
                          key=f"suc_det_{fila.Sucursal}_{fila.Resultado}",
                          on_click=aplicar_seleccion, args=("sucursal", (fila.Sucursal, fila.Resultado)))
    except Exception:
        st.error("No fue posible cargar el dashboard. Verifica la conexión y las versiones de Streamlit y Plotly.")

# =====================================
# CARGA DE ASIG
# =====================================

elif modulo == "Carga de ASIG" and consulta_general:

    st.subheader("📂 Actualización de folios ASIG")

    st.info(
        "El Excel debe contener Serie del Vehículo, "
        "Folio, Estado de atención, Conceptos y Fecha de creación."
    )

    archivo = st.file_uploader(
        "Selecciona el archivo Excel",
        type=["xlsx"]
    )

    if archivo:

        try:

            df = pd.read_excel(
                archivo,
                dtype=str
            ).fillna("")

            df.columns = [
                normalizar_texto(c)
                for c in df.columns
            ]

            columnas = [
                "serie del vehiculo",
                "folio",
                "estado de atencion",
                "conceptos",
                "fecha de creacion"
            ]

            faltantes = [
                c for c in columnas
                if c not in df.columns
            ]

            if faltantes:
                st.error(
                    "Columnas faltantes: "
                    + ", ".join(faltantes)
                )
                st.stop()

            df = df[columnas].copy()

            df.columns = [
                "serie",
                "folio",
                "estado_atencion",
                "conceptos",
                "fecha_creacion"
            ]

            df["serie"] = df["serie"].apply(
                normalizar_serie
            )

            df["folio"] = (
                df["folio"].str.strip().str.upper()
            )

            df["estado_atencion"] = (
                df["estado_atencion"].str.strip()
            )

            df = df[
                (df["serie"] != "") &
                (df["folio"] != "") &
                (df["estado_atencion"] != "")
            ]

            df = df.drop_duplicates(
                subset=["serie", "folio"],
                keep="last"
            )

            fechas_originales = df["fecha_creacion"].copy()
            df["fecha_creacion"] = fechas_originales.apply(interpretar_fecha)
            invalidas = fechas_originales.astype(str).str.strip().ne("") & df["fecha_creacion"].isna()
            df["conceptos"] = df["conceptos"].str.strip()
            st.metric("Folios válidos", len(df))
            st.caption(f"Folios sin fecha de creación: {df['fecha_creacion'].isna().sum():,}")
            if invalidas.any():
                st.error(f"Hay {invalidas.sum():,} fechas no reconocidas. Corrige el Excel antes de cargarlo.")
                st.dataframe(df.loc[invalidas, ["serie", "folio"]].assign(fecha_original=fechas_originales[invalidas]), hide_index=True)
                st.stop()
            if df.empty:
                st.warning("No hay folios válidos para cargar.")
                st.stop()

            st.dataframe(
                df.head(100),
                hide_index=True
            )

            if st.button("💾 Actualizar folios en Supabase"):

                registros = df.to_dict("records")

                for r in registros:
                    r["fecha_actualizacion"] = (
                        datetime.now().astimezone().isoformat()
                    )

                progreso = st.progress(0)

                for inicio in range(
                    0, len(registros), 500
                ):

                    bloque = registros[
                        inicio:inicio + 500
                    ]

                    db.table(
                        "atenciones_vehiculo"
                    ).upsert(
                        bloque,
                        on_conflict="serie,folio"
                    ).execute()

                    progreso.progress(
                        min(
                            (inicio + len(bloque))
                            / len(registros),
                            1.0
                        )
                    )

                st.success(
                    f"{len(registros):,} folios actualizados."
                )

        except Exception:
            st.error(
                "No se completó la carga. "
                "Algunos bloques podrían haberse guardado."
            )

# =====================================
# ADMINISTRACIÓN
# =====================================

elif modulo == "Administración" and es_maestro:

    st.subheader("⚙️ Administración")

    if es_maestro:
        tab1, tab2 = st.tabs(["Usuarios", "Requisitos"])
    else:
        tab2 = st.container()

    if es_maestro:
        with tab1:
            try:
                privado = administrador_privado()
                usuarios = consultar_tabla("perfiles")
                asignaciones = privado.table("usuario_sucursales").select("*").execute().data
                st.dataframe(pd.DataFrame([{
                    "Nombre": u["nombre"], "Usuario": u.get("usuario"), "Rol": u["rol"],
                    "Activo": u["activo"], "Sucursales": "Todas" if u["rol"] != "capturista" else ", ".join(mapa_sucursales.get(a["sucursal_id"], str(a["sucursal_id"])) for a in asignaciones if a["usuario_id"] == u["id"])
                } for u in usuarios]), hide_index=True, use_container_width=True)
                if st.session_state.pop("mensaje_usuario", False):
                    st.success("Cambios guardados.")
                st.markdown("### Nuevo usuario")
                with st.form("alta_usuario", clear_on_submit=False):
                    nombre = st.text_input("Nombre completo")
                    login = st.text_input("Nombre de usuario")
                    clave = st.text_input("Contraseña inicial (mínimo 8 caracteres)", type="password")
                    rol = st.selectbox("Rol", ROLES, format_func=ETIQUETAS.get)
                    sedes = st.multiselect("Sucursales (obligatorio para capturistas)", list(mapa_sucursales), format_func=mapa_sucursales.get)
                    alta = st.form_submit_button("Crear usuario")
                if alta:
                    login = login.strip().lower()
                    if not nombre.strip() or not re.fullmatch(r"[a-z0-9_.-]+", login) or len(clave) < 8 or (rol == "capturista" and not sedes):
                        st.warning("Completa los datos, utiliza un usuario sin espacios y una contraseña de al menos 8 caracteres.")
                    elif any(u.get("usuario") == login for u in usuarios):
                        st.warning("El usuario ya existe.")
                    else:
                        privado = administrador_privado()
                        nuevo = privado.auth.admin.create_user({"email": f"{uuid.uuid4().hex}@casanova.example", "password": clave, "email_confirm": True}).user.id
                        try:
                            privado.table("perfiles").upsert({"id": nuevo, "nombre": nombre.strip(), "usuario": login, "rol": rol, "activo": False}).execute()
                            if sedes and rol == "capturista":
                                privado.table("usuario_sucursales").insert([{"usuario_id": nuevo, "sucursal_id": x} for x in sedes]).execute()
                            privado.table("perfiles").update({"activo": True}).eq("id", nuevo).execute()
                        except Exception:
                            privado.table("perfiles").update({"activo": False}).eq("id", nuevo).execute()
                            st.error("Alta incompleta. Revisa la cuenta en Supabase antes de reintentar.")
                            st.stop()
                        st.session_state.mensaje_usuario = True
                        st.rerun()
                if usuarios:
                    st.markdown("### Editar usuario")
                    mapa = {u["id"]: u for u in usuarios}
                    elegido = st.selectbox("Seleccionar cuenta", list(mapa), format_func=lambda x: f'{mapa[x]["nombre"]} | {mapa[x].get("usuario")}')
                    u = mapa[elegido]
                    actuales = [a["sucursal_id"] for a in asignaciones if a["usuario_id"] == elegido and a["sucursal_id"] in mapa_sucursales]
                    with st.form(f"editar_usuario_{elegido}"):
                        nombre = st.text_input("Nombre", value=u["nombre"])
                        login = st.text_input("Usuario", value=u.get("usuario") or "")
                        rol = st.selectbox("Rol", ROLES, index=ROLES.index(u["rol"]), format_func=ETIQUETAS.get)
                        activo = st.checkbox("Cuenta activa", value=u["activo"])
                        sedes = st.multiselect("Sucursales", list(mapa_sucursales), default=actuales, format_func=mapa_sucursales.get)
                        clave = st.text_input("Nueva contraseña (dejar vacío para conservar)", type="password")
                        guardar = st.form_submit_button("Guardar usuario")
                    if guardar:
                        login = login.strip().lower()
                        if not nombre.strip() or not re.fullmatch(r"[a-z0-9_.-]+", login) or (clave and len(clave)<8) or (rol == "capturista" and not sedes):
                            st.warning("Revisa los datos y la longitud de la contraseña (8 caracteres).")
                        elif elegido == usuario_id and (not activo or rol != "maestro"):
                            st.warning("No puedes desactivar ni quitar tu propio rol de administrador.")
                        elif any(x["id"] != elegido and x.get("usuario") == login for x in usuarios):
                            st.warning("El nombre de usuario ya existe.")
                        else:
                            privado = administrador_privado()
                            cambios = {}
                            if clave: cambios["password"] = clave
                            if cambios: privado.auth.admin.update_user_by_id(elegido, cambios)
                            if elegido != usuario_id:
                                privado.table("perfiles").update({"activo": False}).eq("id", elegido).execute()
                            privado.table("usuario_sucursales").delete().eq("usuario_id", elegido).execute()
                            if rol == "capturista" and sedes:
                                privado.table("usuario_sucursales").insert([{"usuario_id": elegido, "sucursal_id": x} for x in sedes]).execute()
                            privado.table("perfiles").update({"nombre": nombre.strip(), "usuario": login, "rol": rol, "activo": activo}).eq("id", elegido).execute()
                            st.session_state.mensaje_usuario = True
                            st.rerun()
            except Exception as error:
                codigo = getattr(error, "code", None)
                estado = getattr(error, "status", None)
                st.error("No se completó la operación de usuarios. Revisa Secrets y los datos antes de reintentar.")
                st.caption(f"Diagnóstico: {type(error).__name__} | código: {codigo or 'no disponible'} | estado: {estado or 'no disponible'}")

    with tab2:

        try:

            requisitos = (
                db.table("checklist_requisitos")
                .select("*")
                .order("orden")
                .execute()
                .data
            )

            st.dataframe(
                pd.DataFrame(requisitos),
                hide_index=True
            )

            if requisitos:

                mapa = {
                    r["id"]: r
                    for r in requisitos
                }

                elegido = st.selectbox(
                    "Seleccionar requisito",
                    list(mapa.keys()),
                    format_func=lambda x: (
                        mapa[x]["requisito"]
                    )
                )

                actual = mapa[elegido]

                with st.form(
                    f"editar_requisito_{elegido}"
                ):

                    activo = st.checkbox(
                        "Requisito activo",
                        value=bool(actual["activo"])
                    )

                    orden = st.number_input(
                        "Orden",
                        min_value=1,
                        value=int(actual["orden"])
                    )

                    guardar = st.form_submit_button(
                        "Guardar cambios"
                    )

                if guardar:

                    db.table(
                        "checklist_requisitos"
                    ).update({
                        "activo": activo,
                        "orden": int(orden)
                    }).eq(
                        "id", elegido
                    ).execute()

                    st.rerun()

            st.markdown("### Agregar requisito")

            with st.form("nuevo_requisito"):

                categoria = st.text_input("Categoría")
                requisito = st.text_input("Requisito")
                requiere_fecha = st.checkbox(
                    "Solicitar fecha"
                )
                nombre_fecha = st.text_input(
                    "Nombre del campo de fecha"
                )

                orden = st.number_input(
                    "Orden del nuevo requisito",
                    min_value=1,
                    value=8
                )

                agregar = st.form_submit_button(
                    "Agregar requisito"
                )

            if agregar:

                if not categoria.strip() or not requisito.strip():
                    st.warning(
                        "Completa la categoría y el requisito."
                    )

                elif requiere_fecha and not nombre_fecha.strip():
                    st.warning("Indica el nombre de la fecha.")

                elif any(
                    normalizar_texto(r["requisito"])
                    == normalizar_texto(requisito)
                    for r in requisitos
                ):
                    st.warning("El requisito ya existe.")

                else:

                    db.table(
                        "checklist_requisitos"
                    ).insert({
                        "categoria": categoria.upper(),
                        "requisito": requisito.upper(),
                        "requiere_fecha": requiere_fecha,
                        "nombre_campo_fecha": (
                            nombre_fecha.upper()
                            if requiere_fecha else None
                        ),
                        "activo": True,
                        "orden": int(orden)
                    }).execute()

                    st.rerun()

        except Exception:
            st.error(
                "No fue posible administrar los requisitos."
            )


elif modulo == "Mi contraseña":
    st.subheader("Cambiar mi contraseña")
    with st.form("cambiar_clave"):
        anterior = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Nueva contraseña (mínimo 8 caracteres)", type="password")
        confirmar = st.text_input("Confirmar nueva contraseña", type="password")
        cambiar = st.form_submit_button("Cambiar contraseña")
    if cambiar:
        if len(nueva) < 8 or nueva != confirmar:
            st.warning("La contraseña debe tener al menos 8 caracteres y coincidir con la confirmación.")
        else:
            try:
                correo = db.auth.get_user().user.email
                db.auth.sign_in_with_password({"email": correo, "password": anterior})
                db.auth.update_user({"password": nueva})
                st.success("Contraseña actualizada.")
            except Exception:
                st.error("No se pudo cambiar la contraseña. Verifica la contraseña actual.")
