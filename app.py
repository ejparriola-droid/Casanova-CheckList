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
