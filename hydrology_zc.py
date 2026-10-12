"""Fuentes INA locales. No convierte niveles de río en alertas meteorológicas."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

TZ = "America/Argentina/Buenos_Aires"
INA_PRODUCTO = "https://www.ina.gov.ar/alerta/index.php?seccion=10"
INA_VISOR = "https://alerta.ina.gob.ar/"
INA_OBS_BASE = "https://alerta.ina.gob.ar/pub/datos/datos&"
ESTACIONES = {
    "Zárate": {"observada": 40, "pronostico": 29534},
    "Campana": {"observada": 41, "pronostico": 3405},
}
ENLACES = {
    "Prefectura · alturas observadas": "https://contenidosweb.prefecturanaval.gob.ar/alturas/",
    "SHN · contexto mareológico del estuario": "https://www.hidro.gov.ar/oceanografia/pronostico.asp",
    "Municipalidad de Zárate · teléfonos": "https://zarate.gob.ar/telefonos-utiles/",
    "Municipalidad de Campana · teléfonos": "https://www.campana.gob.ar/telefonos-utiles/",
}


def url_pronostico(serie_id: int) -> str:
    return ("https://alerta.ina.gob.ar/a5/sim/calibrados/489/corridas/last?"
            + urlencode({"group_by_qualifier": "true", "includeProno": "true", "series_id": serie_id}))


def _fecha_utc(valor):
    fecha = pd.to_datetime(valor, errors="coerce", utc=True)
    return fecha if pd.notna(fecha) else None


def parsear_pronostico(payload, serie_id: int, referencia=None) -> dict:
    """Valida identidad de corrida/serie y conserva sólo horas futuras (máximo 4 días)."""
    referencia = pd.Timestamp(referencia or datetime.now(timezone.utc))
    referencia = referencia.tz_localize("UTC") if referencia.tzinfo is None else referencia.tz_convert("UTC")
    if not isinstance(payload, dict) or payload.get("cal_id") != 489:
        raise ValueError("La corrida no corresponde al producto INA configurado.")
    emision = _fecha_utc(payload.get("forecast_date"))
    if emision is None or emision > referencia + pd.Timedelta(minutes=15):
        raise ValueError("La fecha de emisión de la corrida es inválida.")
    if not isinstance(payload.get("series"), list):
        raise ValueError("La fuente no devolvió series de pronóstico.")
    partes = {}
    for serie in payload["series"]:
        if not isinstance(serie, dict) or serie.get("series_id") != serie_id:
            continue
        etiqueta = serie.get("qualifier")
        if etiqueta not in {"main", "error_band_01", "error_band_99"}:
            continue
        if serie.get("cor_id") != payload.get("id"):
            raise ValueError("La serie y la corrida no coinciden.")
        filas = []
        for fila in serie.get("pronosticos", []):
            if not isinstance(fila, dict):
                continue
            fecha = _fecha_utc(fila.get("timestart"))
            try:
                valor = float(fila["valor"])
            except (KeyError, TypeError, ValueError):
                continue
            if fecha is not None and np.isfinite(valor) and referencia <= fecha <= referencia + pd.Timedelta(hours=96):
                filas.append({"fecha": fecha, etiqueta: valor})
        if filas:
            partes[etiqueta] = pd.DataFrame(filas).drop_duplicates("fecha", keep="last").set_index("fecha")
    if "main" not in partes:
        raise ValueError("No hay pronóstico principal para las próximas horas.")
    df = partes["main"]
    for etiqueta in ("error_band_01", "error_band_99"):
        if etiqueta in partes:
            df = df.join(partes[etiqueta], how="left")
    if {"error_band_01", "error_band_99"}.issubset(df.columns):
        invertida = df.error_band_01 > df.error_band_99
        df.loc[invertida, ["error_band_01", "error_band_99"]] = np.nan
    df = df.sort_index().reset_index()
    df["fecha"] = df["fecha"].dt.tz_convert(TZ)
    return {"df": df, "emision": emision.tz_convert(TZ), "serie_id": serie_id,
            "corrida_id": payload["id"], "atrasado": referencia - emision > pd.Timedelta(hours=6)}


@st.cache_data(ttl=600, show_spinner=False)
def obtener_pronostico(serie_id: int) -> dict:
    url = url_pronostico(serie_id)
    try:
        r = requests.get(url, headers={"User-Agent": "ALA-Zarate-Campana/1.0"}, timeout=(5, 15))
        r.raise_for_status()
        resultado = parsear_pronostico(r.json(), serie_id)
        return {**resultado, "url": url, "error": ""}
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return {"df": pd.DataFrame(), "url": url,
                "error": "No se pudo verificar el pronóstico INA de esta estación. Consultá el producto oficial."}


def parsear_observaciones(payload, serie_id: int) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise ValueError("Respuesta de observaciones inválida.")
    meta = payload.get("responseHeader", {}).get("seriesmetadata", {})
    if str(meta.get("seriesId")) != str(serie_id) or str(meta.get("unitId")) != "11":
        raise ValueError("Identidad o unidad de observaciones no verificada.")
    filas = []
    for fila in payload.get("data", []):
        try:
            valor = float(fila["valor"])
            fecha = pd.to_datetime(fila["timestart"], errors="raise")
            fecha = fecha.tz_localize(TZ) if fecha.tzinfo is None else fecha.tz_convert(TZ)
            if np.isfinite(valor):
                filas.append({"fecha": fecha, "observado": valor})
        except (KeyError, TypeError, ValueError):
            continue
    if not filas:
        raise ValueError("Sin observaciones numéricas verificables.")
    return pd.DataFrame(filas).sort_values("fecha").drop_duplicates("fecha", keep="last")


@st.cache_data(ttl=600, show_spinner=False)
def obtener_observaciones(serie_id: int) -> dict:
    hoy = datetime.now(ZoneInfo(TZ)).date()
    url = INA_OBS_BASE + urlencode({"seriesId": serie_id, "timeStart": str(hoy - timedelta(days=7)),
                                  "timeEnd": str(hoy + timedelta(days=1)), "format": "json"})
    try:
        r = requests.get(url, headers={"User-Agent": "ALA-Zarate-Campana/1.0"}, timeout=(5, 12))
        r.raise_for_status()
        return {"df": parsear_observaciones(r.json(), serie_id), "url": url, "error": ""}
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return {"df": pd.DataFrame(), "url": url,
                "error": "Observaciones INA no verificadas: no se informa altura actual ni se asigna cero."}


def mostrar_panel_ina():
    st.subheader("🌊 Paraná de las Palmas · Zárate y Campana")
    st.warning("El semáforo meteorológico no mide la crecida del río ni la sudestada. "
               "Un resultado verde por lluvia no confirma seguridad en costas, islas o bajos.")
    st.write("Pronóstico experimental del INA a cuatro días, con emisión y disponibilidad visibles. "
             "Las alturas corresponden a la escala de cada estación; no son la profundidad de agua en un barrio.")
    if st.button("Actualizar consultas del río", key="zc_ina_refresh"):
        obtener_pronostico.clear()
        obtener_observaciones.clear()
    with st.spinner("Consultando pronósticos locales del INA…"):
        with ThreadPoolExecutor(max_workers=2) as pool:
            pronosticos = list(pool.map(obtener_pronostico, [v["pronostico"] for v in ESTACIONES.values()]))
    for col, (nombre, config), resultado in zip(st.columns(2), ESTACIONES.items(), pronosticos):
        with col:
            st.markdown(f"### {nombre}")
            if resultado["error"]:
                st.warning(resultado["error"])
            else:
                df = resultado["df"]
                st.caption(f"Emisión: {resultado['emision']:%d/%m/%Y %H:%M} ART · "
                           f"serie {config['pronostico']} · corrida {resultado['corrida_id']}")
                if resultado["atrasado"]:
                    st.warning("Corrida de más de seis horas: verificar una actualización en el INA. "
                               "Se muestra como pronóstico atrasado, sin evaluación de seguridad.")
                maximo = df.loc[df.main.idxmax()]
                st.metric("Máximo previsto en el período disponible", f"{maximo['main']:.2f} m")
                st.caption(f"Máximo: {maximo['fecha']:%d/%m %H:%M} ART · "
                           f"datos hasta {df.fecha.max():%d/%m %H:%M} ART")
                fig = go.Figure()
                for campo, nombre_serie, color in [("error_band_01", "Banda inferior INA", "#a6cad9"),
                                                  ("error_band_99", "Banda superior INA", "#a6cad9"),
                                                  ("main", "Pronóstico principal", "#168ab0")]:
                    if campo in df:
                        fig.add_trace(go.Scatter(x=df.fecha, y=df[campo], name=nombre_serie,
                                                 mode="lines", line={"color": color},
                                                 hovertemplate="%{x|%d/%m %H:%M}<br>%{y:.2f} m<extra>%{fullData.name}</extra>"))
                fig.update_layout(height=330, margin={"l": 15, "r": 15, "t": 20, "b": 15},
                                  yaxis_title="Altura en la escala de la estación (m)",
                                  xaxis_title="Hora local (ART)", legend={"orientation": "h"})
                st.plotly_chart(fig, use_container_width=True, key="zc_ina_" + str(config["pronostico"]))
                st.download_button("Descargar pronóstico CSV", df.to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"INA_{nombre}_pronostico.csv", mime="text/csv",
                                   key="zc_ina_csv_" + str(config["pronostico"]))
            st.link_button("Abrir pronóstico oficial del INA", INA_PRODUCTO, use_container_width=True)
    st.caption("No se trasladan umbrales de otra estación ni se combinan estas alturas con el índice de lluvia. "
               "La aplicación no determina evacuación por el pronóstico del río. Las bandas son las publicadas por INA.")
    with st.expander("Alturas observadas · consultar serie verificada"):
        nombre = st.selectbox("Estación observada", list(ESTACIONES), key="zc_ina_observada")
        if st.button("Consultar observaciones", key="zc_ina_obs_button"):
            resultado = obtener_observaciones(ESTACIONES[nombre]["observada"])
            if resultado["error"]:
                st.warning(resultado["error"])
            else:
                df = resultado["df"]
                ultimo = df.iloc[-1]
                edad = pd.Timestamp.now(tz=TZ) - ultimo.fecha
                if pd.Timedelta(0) <= edad <= pd.Timedelta(hours=6):
                    st.metric("Última altura observada", f"{ultimo.observado:.2f} m")
                else:
                    st.warning("Serie atrasada o fecha futura: no se interpreta como altura actual.")
                st.caption(f"Última observación: {ultimo.fecha:%d/%m/%Y %H:%M} ART")
                st.line_chart(df.set_index("fecha")[["observado"]], y_label="Altura de escala (m)")
                st.download_button("Descargar observaciones CSV", df.to_csv(index=False).encode("utf-8-sig"),
                                   f"INA_{nombre}_observado.csv", "text/csv", key="zc_ina_obs_csv")
        st.link_button("Consultar visualizador oficial INA", INA_VISOR)
    st.divider()
    st.markdown("**En caso de emergencia:** Defensa Civil **103**, Bomberos **100**, Policía **911**. "
                "En Campana, SAME **107**. Confirmá recorridos y centros de evacuación con el municipio.")
    for etiqueta, url in ENLACES.items():
        st.link_button(etiqueta, url)
    st.caption("El pronóstico mareológico del SHN aporta contexto del estuario; no representa una altura local de Zárate o Campana.")
