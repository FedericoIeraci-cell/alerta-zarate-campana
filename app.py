"""Página retirada por decisión del titular del proyecto."""
import streamlit as st

st.set_page_config(page_title="Proyecto retirado", page_icon="📁", layout="centered")
st.title("Proyecto retirado")
st.info("Alerta Zárate–Campana dejó de estar en funcionamiento el 28 de octubre de 2026.")
st.write("Este sitio ya no consulta datos, muestra evaluaciones ni emite avisos.")
st.caption("El trabajo continúa exclusivamente como trabajo práctico académico sobre Goya, Corrientes.")
st.stop()
