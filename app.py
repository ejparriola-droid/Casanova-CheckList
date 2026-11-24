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
.stApp { background-color: #F5F7FB; }
h1, h2, h3 { color: #213769; }
div.stButton > button {
    background-color: #213769;
    color: white;
    border-radius: 8px;
    border: none;
    font-weight: bold;
}
div[data-testid="stMetric"] {
    background: white;
    border: 1px solid #E5EAF2;
    padding: 12px;
    border-radius: 10px;
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
