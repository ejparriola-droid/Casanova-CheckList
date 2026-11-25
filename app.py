
import streamlit as st
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
    background-color: #F4F7FB;
    color: #17365D;
}
h1, h2, h3, h4, label {
    color: #17365D !important;
}
div[data-testid="stMetric"] {
    background: white;
    border: 1px solid #C7D2E0;
    padding: 15px;
    border-radius: 10px;
}
div[data-testid="stMetricValue"] {
    color: #17365D;
}
div.stButton > button,
div.stDownloadButton > button,
button[kind="primary"] {
    background-color: #174A7E !important;
    color: white !important;
    border-radius: 8px;
}
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

    faltantes = [
        c for c in COLUMNAS
        if c not in df.columns
    ]

    if faltantes:
        raise ValueError(
            "Columnas faltantes: " + ", ".join(faltantes)
        )

    df = df[COLUMNAS].copy()

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

    return df


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
        base[nombre] = ["No aplica a esta revisión" if r is None else "SÍ" if r.get("respuesta") is True else "NO" if r.get("respuesta") is False else "SIN REVISAR" for r in filas]
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
            celda.fill = PatternFill("solid", fgColor="174A7E")
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
                    colores = {"SÍ": ("E2F0D9", "216E39"), "NO": ("FCE4D6", "A4262C"), "SIN REVISAR": ("FFF2CC", "805B10")}
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

        correo = st.text_input("Correo electrónico")

        password = st.text_input(
            "Contraseña",
            type="password"
        )

        entrar = st.form_submit_button(
            "Iniciar sesión"
        )

    if entrar:

        try:
            resultado = db.auth.sign_in_with_password({
                "email": correo.strip(),
                "password": password
            })

            st.session_state.usuario_id = (
                resultado.user.id
            )

            st.rerun()

        except Exception:
            st.error("Correo o contraseña incorrectos.")

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

es_admin = (
    str(perfil["rol"]).lower() == "administrador"
)

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

st.sidebar.caption(
    "Administrador" if es_admin else "Capturista"
)

opciones = [
    "Capturar checklist",
    "Historial"
]

if es_admin:
    opciones += [
        "Dashboard",
        "Carga de ASIG",
        "Administración"
    ]

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

if modulo == "Capturar checklist":

    st.subheader("🔎 Consulta de vehículos")

    if not mapa_sucursales:
        st.warning("No tienes una sucursal asignada.")
        st.stop()

    sucursal_id = st.selectbox(
        "Sucursal de captura",
        list(mapa_sucursales.keys()),
        format_func=lambda x: mapa_sucursales[x]
    )

    if st.button("🔄 Actualizar base maestra"):
        cargar_base.clear()
        st.rerun()

    try:
        df = cargar_base()

        st.success(
            f"Base conectada | {len(df):,} vehículos"
        )

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
        c2.metric("Versión", mostrar(unidad["Version"]))
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
            "**Fecha de compra:**",
            mostrar(unidad["Fecha Compra"])
        )

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

        respuestas = []

        with st.form(f"checklist_{serie}_{sucursal_id}"):

            categoria_anterior = None

            for r in requisitos:

                if r["categoria"] != categoria_anterior:

                    st.markdown(
                        f"### {r['categoria'].upper()}"
                    )

                    categoria_anterior = r["categoria"]

                clave = f"{serie}_{sucursal_id}_{r['id']}"

                respuesta = st.radio(
                    r["requisito"].upper(),
                    ["Sin revisar", "Sí", "No"],
                    horizontal=True,
                    key=f"respuesta_{clave}"
                )

                fecha = None

                if r["requiere_fecha"]:

                    fecha = st.date_input(
                        r["nombre_campo_fecha"] or "Fecha",
                        value=None,
                        format="DD/MM/YYYY",
                        min_value=date(1990, 1, 1),
                        max_value=date(2100, 12, 31),
                        key=f"fecha_{clave}"
                    )

                observacion = st.text_input(
                    "Observaciones (opcional)",
                    key=f"obs_{clave}"
                )

                respuestas.append({
                    "requisito_id": r["id"],
                    "respuesta": {
                        "Sí": True,
                        "No": False,
                        "Sin revisar": None
                    }[respuesta],
                    "fecha_vencimiento": (
                        fecha.isoformat()
                        if fecha else None
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
                r["respuesta"] is None
                for r in respuestas
            )

            pendientes = sum(
                r["respuesta"] is False
                for r in respuestas
            )

            if sin_revisar:
                estatus = "Pendiente"
            elif pendientes:
                estatus = "Con pendientes"
            else:
                estatus = "Completo"

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

            revision_id = None

            try:

                resultado = (
                    db.table("checklist_revisiones")
                    .insert(revision)
                    .execute()
                )

                revision_id = resultado.data[0]["id"]

                for r in respuestas:
                    r["revision_id"] = revision_id

                db.table(
                    "checklist_respuestas"
                ).insert(respuestas).execute()

                st.success(
                    f"Checklist guardado correctamente. "
                    f"Registro: {revision_id}"
                )

            except Exception:

                if revision_id is not None:
                    st.error(
                        f"Se creó la revisión {revision_id}, "
                        "pero no se confirmaron sus respuestas. "
                        "Solicita revisión al administrador."
                    )
                else:
                    st.error(
                        "No se confirmó el guardado del checklist. "
                        "Revisa el historial antes de reintentar."
                    )

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

elif modulo == "Dashboard" and es_admin:

    st.subheader("📊 Dashboard general")

    try:

        datos = consultar_tabla(
            "checklist_revisiones"
        )

        df = pd.DataFrame(datos)

        if df.empty:
            st.info("Todavía no hay capturas.")

        else:

            c1, c2, c3, c4 = st.columns(4)

            c1.metric("Checklists", len(df))

            c2.metric(
                "Unidades revisadas",
                df["serie"].nunique()
            )

            c3.metric(
                "Completos",
                int((df["estatus"] == "Completo").sum())
            )

            c4.metric(
                "Con pendientes",
                int((df["estatus"] != "Completo").sum())
            )

            df["Sucursal"] = (
                df["sucursal_id"]
                .map(mapa_sucursales)
            )

            st.markdown("### Capturas por sucursal")

            st.bar_chart(
                df["Sucursal"].value_counts()
            )

            st.markdown("### Estatus de las revisiones")

            st.bar_chart(
                df["estatus"].value_counts()
            )

            st.dataframe(
                df,
                hide_index=True,
                use_container_width=True
            )

            descargar_excel(
                {"Dashboard": df},
                "Dashboard_Casanova.xlsx"
            )

    except Exception:
        st.error("No fue posible cargar el dashboard.")

# =====================================
# CARGA DE ASIG
# =====================================

elif modulo == "Carga de ASIG" and es_admin:

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

elif modulo == "Administración" and es_admin:

    st.subheader("⚙️ Administración")

    tab1, tab2 = st.tabs([
        "Usuarios",
        "Requisitos"
    ])

    with tab1:

        try:

            usuarios = consultar_tabla("perfiles")

            st.dataframe(
                pd.DataFrame(usuarios),
                hide_index=True,
                use_container_width=True
            )

            st.caption(
                "El alta de cuentas y contraseñas "
                "se realiza por ahora en Supabase Auth."
            )

        except Exception:
            st.error("No fue posible consultar usuarios.")

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
