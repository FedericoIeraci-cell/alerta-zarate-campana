"""Resumen público de la evaluación existente; no calcula otro índice de riesgo."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import html
import math
import re
import unicodedata
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Argentina/Buenos_Aires")
ESTACIONES = {"Zárate": (40, 29534), "Campana": (41, 3405)}
FUENTES_ACCIONES = [
    ("SINAGIR · prevención", "https://www.argentina.gob.ar/sinagir/riesgos-frecuentes/inundacion/prevencion"),
    ("SINAGIR · ante una inundación", "https://www.argentina.gob.ar/sinagir/riesgos-frecuentes/inundacion/que-hacer"),
    ("SENASA · preparación de familias y trabajo rural", "https://www.argentina.gob.ar/noticias/recomendaciones-para-prevenir-riesgos-y-reducir-el-impacto-del-fenomeno-del-nino"),
]


def _numero(valor):
    if valor is None or type(valor).__name__ in ("bool", "bool_"):
        return None
    try:
        valor = float(valor)
        return valor if math.isfinite(valor) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _fecha(valor, local=False):
    try:
        if isinstance(valor, str):
            try:
                valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
            except ValueError:
                if not local:
                    return None
                valor = datetime.strptime(valor, "%d/%m/%Y %H:%M")
        if not isinstance(valor, datetime):
            return None
        if valor.tzinfo is None:
            if not local:
                return None
            valor = valor.replace(tzinfo=TZ)
        return valor.astimezone(TZ)
    except (ValueError, TypeError, OverflowError):
        return None


def _vigente(fecha, referencia, horas, tolerancia=0):
    return fecha is not None and -tolerancia <= (referencia-fecha).total_seconds() <= horas*3600


def _hora(fecha, referencia=None):
    if fecha is None:
        return "Fecha sin confirmar"
    texto = fecha.strftime("%d/%m %H:%M ART")
    if referencia is not None:
        minutos = (referencia-fecha).total_seconds()/60
        if minutos >= 0:
            texto += " · hace " + (f"{int(minutos)} min" if minutos < 60 else f"{minutos/60:.1f} h")
    return texto


def _texto(valor):
    return re.sub(r"\s+", " ", str(valor or "")).strip()


def _normal(valor):
    return "".join(c for c in unicodedata.normalize("NFKD", _texto(valor))
                   if not unicodedata.combining(c)).casefold()


def _url(valor, organismos):
    try:
        p = urlparse(_texto(valor))
        if p.scheme == "https" and p.hostname in organismos and not p.username and not p.password and p.port in (None, 443):
            return valor
    except ValueError:
        pass
    return ""


def _valor(valor, decimales=1, unidad=""):
    valor = _numero(valor)
    return "Sin dato actual" if valor is None else f"{valor:.{decimales}f}{unidad}"


def resumir_lluvia(row, referencia):
    fecha = _fecha(row.get("actualizado"), local=True)
    consulta = _fecha(row.get("consulta_meteorologica"))
    vigente = _vigente(fecha, referencia, 12)
    completo = (vigente and row.get("estado_datos") == "OK"
                and bool(row.get("cobertura_meteorologica")) and _numero(row.get("indice")) is not None)
    valores = {c: _numero(row.get(c)) if vigente else None for c in
               ("lluvia_futura_24", "lluvia_futura_72", "lluvia_futura_7d", "humedad_suelo_promedio", "runoff_futuro_72")}
    nivel = row.get("nivel", "SIN DATOS") if completo else "SIN DATOS"
    estado = "Datos meteorológicos completos" if completo else "Datos parciales" if vigente and any(v is not None for v in valores.values()) else "Actualizar meteorología"
    return {"estado": estado, "vigente": vigente, "completo": completo, "nivel": nivel,
            "indice": _numero(row.get("indice")) if completo else None, "valores": valores,
            "fecha": fecha, "consulta": consulta,
            "referencia": _fecha(row.get("referencia_datos"), local=True),
            "fuente": "https://api.open-meteo.com/v1/ecmwf",
            "faltante": "" if completo else "Meteorología incompleta o antigua: revisar lluvia, suelo y su fecha."}


def resumir_rio(partido, rio, previsiones, referencia):
    serie, serie_pronostico = ESTACIONES.get(partido, (None, None))
    rio = rio if isinstance(rio, dict) else {}
    fecha = _fecha(rio.get("fecha"))
    fuente = _url(rio.get("fuente"), {"alerta.ina.gob.ar", "alerta.ina.gov.ar", "www.ina.gov.ar", "www.ina.gob.ar"})
    identidad = serie is not None and rio.get("serie_id") == serie
    actual = (identidad and bool(fuente) and rio.get("observacion_vigente") is True
              and _vigente(fecha, referencia, 6) and not rio.get("error"))
    altura = _numero(rio.get("altura_m")) if actual else None
    alerta = _numero(rio.get("alerta_m")) if identidad and rio.get("umbral_publicado") is True else None
    evacuacion = _numero(rio.get("evacuacion_m")) if alerta is not None else None
    if evacuacion is not None and evacuacion <= alerta:
        alerta = evacuacion = None
    if altura is None:
        estado = "Altura actual sin confirmar"
    elif alerta is None:
        estado = "Altura disponible · umbral por confirmar"
    elif altura >= alerta:
        estado = "Alcanza referencia INA de evacuación" if evacuacion is not None and altura >= evacuacion else "Alcanza referencia INA de alerta"
    else:
        estado = "Por debajo de la referencia de alerta"
    prono = next((p for p in previsiones if isinstance(p, dict) and p.get("estacion") == partido
                  and p.get("serie_pronostico") == serie_pronostico and p.get("id") == "corto"), {})
    emision = _fecha(prono.get("emision"))
    fin = _fecha(prono.get("fin_publicado"))
    fuente_prono = _url(prono.get("fuente"), {"alerta.ina.gob.ar", "alerta.ina.gov.ar"})
    prono_actual = bool(fuente_prono and prono.get("vigente") is True and _vigente(emision, referencia, 6, 300)
                        and fin is not None and referencia <= fin <= referencia+timedelta(hours=96))
    return {"estacion": partido, "serie": serie, "serie_pronostico": serie_pronostico,
            "estado": estado, "vigente": altura is not None, "altura": altura, "fecha": fecha,
            "alerta": alerta, "evacuacion": evacuacion, "fuente": fuente,
            "pronostico_vigente": prono_actual,
            "maximo_previsto": _numero(prono.get("maximo_m_serie_pronostico")) if prono_actual else None,
            "emision_pronostico": emision, "fin_pronostico": fin, "fuente_pronostico": fuente_prono,
            "comparacion_pronostico_umbral": False,
            "faltante": "" if altura is not None and alerta is not None else
                f"{partido}: altura actual o referencia de la misma escala por confirmar."}


def resumir_represa(cuenca, referencia):
    parte = (cuenca or {}).get("eby") or {}
    consulta = _fecha(parte.get("consulta"))
    try:
        dia = date.fromisoformat(str(parte.get("fecha_informe")))
    except (ValueError, TypeError):
        dia = None
    fuente = _url(parte.get("url"), {"eby.gov.py", "www.eby.gov.py"})
    reciente = bool(fuente and not parte.get("error") and dia is not None
                    and 0 <= (referencia.date()-dia).days <= 1 and _vigente(consulta, referencia, 24, 300))
    campos = parte.get("campos") if isinstance(parte.get("campos"), list) else []
    afluencia = next((c for c in campos if isinstance(c, dict) and c.get("variable") == "caudal_afluente_hoy"
                     and c.get("unidad") in ("m³/s", "m3/s") and c.get("tipo") == "pronosticado"), {})
    valor = _numero(afluencia.get("valor")) if reciente else None
    if valor is not None and valor < 0:
        valor = None
    return {"estado": "Parte de Yacyretá reciente" if reciente else "Parte de Yacyretá sin actualidad confirmada",
            "reciente": reciente, "fecha_documento": dia, "consulta": consulta,
            "afluencia_prevista": valor, "fecha_afluencia": afluencia.get("fecha"),
            "fuente": fuente or "https://eby.gov.py/category/nivelembalse/",
            "llegada_local": None,
            "faltante": "" if reciente else "Represas: falta un parte reciente verificado de Yacyretá."}


def resumir_smn(row, cap, referencia):
    cap = cap if isinstance(cap, dict) else {}
    feed, consulta = _fecha(cap.get("fecha_feed")), _fecha(cap.get("consultado"))
    canal = not cap.get("error") and all(_vigente(f, referencia, 24, 300) for f in (feed, consulta))
    completo = canal and isinstance(cap.get("filas"), list) and not any(cap.get(k) for k in ("fallos", "truncado", "fechas_no_confirmadas_locales", "replacements_no_confirmados"))
    documentos = cap.get("filas") if isinstance(cap.get("filas"), list) else []
    reemplazados = {str(r) for d in documentos if isinstance(d, dict) and d.get("status") == "Actual"
                   and d.get("tipo_mensaje") in ("Cancel", "Update") and _fecha(d.get("emision")) is not None
                   and _fecha(d.get("emision")) <= referencia+timedelta(minutes=5) for r in (d.get("referencias") or [])}
    avisos = []
    localidad, partido = _normal(row.get("localidad")), _normal(row.get("partido"))
    if not localidad or not partido:
        completo = False
    for d in documentos:
        if not isinstance(d, dict) or not canal or d.get("status") != "Actual" or d.get("tipo_mensaje") not in ("Alert", "Update") or str(d.get("id")) in reemplazados:
            continue
        emision = _fecha(d.get("emision"))
        inicio, fin = _fecha(d.get("desde")) or emision, _fecha(d.get("hasta"))
        local = (bool(localidad) and localidad in {_normal(n) for n in (d.get("nodos") or [])}
                 or (bool(partido) and not d.get("poligonos") and bool(re.search(r"\b"+re.escape(partido)+r"\b",
                                                              _normal(" ".join(d.get("areas") or []))))))
        fuente = _url(d.get("url"), {"ssl.smn.gob.ar", "www.smn.gob.ar", "smn.gob.ar"})
        if local and (not fuente or emision is None or emision > referencia+timedelta(minutes=5)
                      or inicio is None or fin is None or fin <= inicio or fin < emision):
            completo = False
        if not (local and fuente and emision is not None and emision <= referencia+timedelta(minutes=5)
                and inicio is not None and fin is not None and fin > referencia and fin > inicio and fin >= emision):
            continue
        avisos.append({"fenomeno": _texto(d.get("fenomeno") or d.get("titulo")),
                       "inicio": inicio, "fin": fin, "emision": emision, "fuente": fuente,
                       "estado": "Vigente" if inicio <= referencia else "Previsto",
                       "severidad": _texto(d.get("severidad_cap"))})
    estado = f"{len(avisos)} aviso(s) para esta referencia" if avisos else "Sin avisos locales en la consulta" if completo else "Cobertura SMN por confirmar"
    return {"estado": estado, "completo": completo, "avisos": avisos, "fecha": feed,
            "fuente": "https://www.smn.gob.ar/alertas",
            "faltante": "" if completo else "SMN: la lectura parcial o antigua no confirma ausencia de avisos."}


def construir_portada_zc(row, decision=None, modelo=None, rio=None, cap=None, cuenca=None, referencia=None):
    """Reutiliza la prioridad regional y muestra la evidencia propia del punto elegido."""
    referencia = _fecha(referencia or datetime.now(timezone.utc))
    if referencia is None:
        raise ValueError("La portada necesita una referencia con zona horaria.")
    row = dict(row)
    decision = decision if isinstance(decision, dict) else {}
    modelo = modelo if isinstance(modelo, dict) else {}
    lluvia = resumir_lluvia(row, referencia)
    rio = resumir_rio(row.get("partido", ""), rio, modelo.get("rios") or [], referencia)
    represa = resumir_represa(cuenca, referencia)
    smn = resumir_smn(row, cap, referencia)
    prioridad = decision.get("prioridad")
    if type(prioridad).__name__ in ("bool", "bool_") or prioridad not in (0, 1, 2):
        prioridad = None
    motivos = [_texto(m) for m in (decision.get("motivos") or []) if _texto(m)]
    relevantes = [m for m in motivos if any(t in _normal(m) for t in
                  ("altura observada alcanza", "agua reportada", "acceso reportado cerrado", "smn:", "modelo local", "aguas altas", "tendencia ascendente"))]
    # Conservar visibles todos los cruces y partes locales que exigen atención;
    # un aviso de menor intensidad no debe ocultarlos por aparecer primero.
    criticos = [m for m in motivos if any(t in _normal(m) for t in
                ("altura observada alcanza", "agua reportada", "acceso reportado cerrado", "nivel experimental rojo"))]
    senales = [a for a in (modelo.get('alertas') or []) if isinstance(a,dict)
               and a.get('prioridad') == prioridad and prioridad in (1,2)]
    causas_modelo = [_texto(a.get('localidad') or 'Sector local')+' · '+_texto(a.get('nivel'))+
                     ' · '+_texto(a.get('horizonte') or 'Plazo por confirmar') for a in senales[:3]]
    causas = list(dict.fromkeys(criticos + causas_modelo + [m for m in relevantes if m not in criticos][:2]))
    if not causas:
        causas = motivos[:2] or ["Faltan datos verificados para describir la situación regional."]
    causa = causas[0]
    faltantes = [bloque["faltante"] for bloque in (lluvia, rio, represa, smn) if bloque["faltante"]]
    dudas = [_texto(x) for x in (decision.get("incertidumbres") or []) if _texto(x)]
    if any("acceso" in _normal(x) or "parte" in _normal(x) for x in dudas) or not decision:
        faltantes.append("Confirmar agua presente, accesos y destinos con la autoridad de cada sector.")
    return {"localidad": _texto(row.get("localidad")), "partido": _texto(row.get("partido")),
            "referencia": referencia, "fecha_evaluacion": _fecha(modelo.get("emision")),
            "prioridad": prioridad,
            "estado_regional": _texto(decision.get("nivel_preparacion")) or "VERIFICACIÓN PENDIENTE",
            "alcance_estado": "Zárate–Campana · preparación regional", "causa": causa, "causas": causas, "motivos": motivos,
            "lluvia": lluvia, "rio": rio, "represa": represa, "smn": smn,
            "faltantes": list(dict.fromkeys(faltantes)), "incertidumbres": dudas,
            "orden_evacuacion": None, "llegada_crecida": None}


def acciones_portada_zc(prioridad, publico):
    """Orientación de preparación; nunca convierte una prioridad en orden de salida."""
    if publico == "Productor / trabajo rural":
        primeras = [
            "Confirmá acceso y comunicación antes de ir al campo o mover hacienda; revisá el parte de tu sector.",
            "Prepará un lugar alto y accesible para animales e insumos, con destino y traslado confirmados.",
            "Antes de ingresar maquinaria, comprobá el suelo y los accesos. Suspendé la tarea si hay agua o condiciones sin verificar.",
        ]
    else:
        primeras = [
            "Prepará documentos protegidos, medicación, linterna y teléfono cargado.",
            "Acordá contactos y asistencia para quienes la necesiten; incluí a tus mascotas.",
            "En costas e islas, confirmá comunicación, acceso y un destino habilitado antes de desplazarte.",
        ]
    if prioridad == 2:
        primeras.insert(0, "Coordiná ahora con Defensa Civil la preparación y la asistencia para los sectores indicados.")
    elif prioridad is None:
        primeras.insert(0, "Verificá las fuentes que faltan antes de decidir una salida o una tarea.")
    return primeras[:4]


def mostrar_portada_zc(st, resumen):
    ref = resumen["referencia"]
    st.subheader("Qué pasa y cómo prepararte")
    etiquetas = {2: "🟠 Atención preventiva alta", 1: "🟡 Preparar medidas", 0: "🔵 Mantener vigilancia", None: "⚪ Verificación pendiente"}
    st.markdown("### " + etiquetas[resumen["prioridad"]])
    st.caption(resumen["alcance_estado"] + " · evaluación: " + _hora(resumen["fecha_evaluacion"], ref))
    st.markdown('**Qué motiva esta preparación**')
    for causa in resumen['causas']:
        st.write('• '+causa)
    st.caption("La preparación abarca los sectores mencionados en la evidencia. La lluvia y el río de tu referencia se muestran por separado; un color meteorológico bajo no descarta una crecida.")
    publico = st.radio("Ver acciones para", ["Mi hogar / mi comunidad", "Productor / trabajo rural"],
                       horizontal=True, key="zc_portada_publico")
    with st.container(border=True):
        st.markdown("**Qué hacer ahora**")
        for accion in acciones_portada_zc(resumen["prioridad"], publico):
            st.write("• " + accion)
        st.caption("Si hay agua creciente o peligro: no cruces agua y pedí asistencia. Seguí las indicaciones de la autoridad local para resguardo o evacuación.")

    lluvia, rio, represa, smn = (resumen[k] for k in ("lluvia", "rio", "represa", "smn"))
    for bloques in (("lluvia", "rio"), ("represa", "smn")):
        columnas = st.columns(2)
        for columna, bloque in zip(columnas, bloques):
            with columna:
                with st.container(border=True):
                    if bloque == "lluvia":
                        st.markdown("#### 🌧️ Lluvia en " + resumen["localidad"])
                        st.write(lluvia["estado"])
                        st.metric("Próximas 24 horas", _valor(lluvia["valores"]["lluvia_futura_24"], 1, " mm"))
                        st.write("**72 horas:** " + _valor(lluvia["valores"]["lluvia_futura_72"], 1, " mm") +
                                 " · **7 días:** " + _valor(lluvia["valores"]["lluvia_futura_7d"], 1, " mm"))
                        st.caption("Índice meteorológico: " + lluvia["nivel"] + " · " + _valor(lluvia["indice"], 1, "/100"))
                        st.caption("Acumulados desde: " + _hora(lluvia['referencia']) + ". Las ventanas de 24 y 72 horas parten de esta referencia.")
                        st.caption("Consulta: " + _hora(lluvia["consulta"], ref) + ". La API no informa la emisión de la corrida. Lluvia estimada por el modelo, no medición local.")
                        st.link_button("Fuente meteorológica · Open-Meteo", lluvia["fuente"], key="zc_portada_lluvia")
                    elif bloque == "rio":
                        st.markdown("#### 🌊 Río en " + rio["estacion"])
                        st.write(rio["estado"])
                        st.metric("Altura observada vigente", _valor(rio["altura"], 2, " m"))
                        st.caption("Registro: " + _hora(rio["fecha"], ref) + " · estación INA " + str(rio["serie"]))
                        if rio["alerta"] is not None:
                            st.write("Referencia de alerta: **" + _valor(rio["alerta"], 2, " m") + "** en la misma escala.")
                        if rio["pronostico_vigente"]:
                            st.caption("Pronóstico INA disponible hasta " + _hora(rio["fin_pronostico"]) +
                                       ". No está confirmada su equivalencia con la escala observada; se revisa en Suelo y ríos.")
                        else:
                            st.caption("Pronóstico local del río: actualidad por confirmar.")
                        st.caption("Altura de la escala del puerto; no es profundidad en una calle o vivienda.")
                        st.link_button("Fuente del río · INA", rio["fuente"] or "https://alerta.ina.gob.ar/", key="zc_portada_rio")
                    elif bloque == "represa":
                        st.markdown("#### 🏞️ Represas aguas arriba")
                        st.write(represa["estado"])
                        dia = represa["fecha_documento"]
                        st.caption("Fecha del parte: " + (dia.strftime("%d/%m/%Y") if dia else "Sin confirmar") + " · fecha documental, sin hora de medición.")
                        if represa["afluencia_prevista"] is not None:
                            st.metric("Afluencia prevista a Yacyretá", _valor(represa["afluencia_prevista"], 0, " m³/s"))
                            st.caption("Día de la previsión: " + _texto(represa["fecha_afluencia"]) + ". No es descarga total ni altura local.")
                        st.caption("Este contexto ayuda a seguir la cuenca. No permite calcular la hora de llegada de una crecida a tu zona.")
                        st.link_button("Parte original · Yacyretá", represa["fuente"], key="zc_portada_represa")
                    else:
                        st.markdown("#### 🚨 Avisos oficiales SMN")
                        st.write(smn["estado"])
                        st.caption("Publicación del canal: " + _hora(smn["fecha"], ref))
                        for i, aviso in enumerate(smn["avisos"][:2]):
                            st.write("**" + aviso["estado"] + " · " + aviso["fenomeno"] + "**")
                            st.caption(_hora(aviso["inicio"]) + " a " + _hora(aviso["fin"]))
                            st.link_button("Abrir aviso oficial", aviso["fuente"], key="zc_portada_smn_"+str(i))
                        st.caption("La coincidencia corresponde al punto o al partido mencionado; revisá el área exacta del aviso.")
                        st.link_button("Todos los avisos · SMN", smn["fuente"], key="zc_portada_smn")
    if resumen["faltantes"]:
        st.markdown("**Qué falta confirmar para decidir**")
        for falta in resumen["faltantes"]:
            st.write("• " + falta)
    st.caption("Una preparación preventiva no es una orden de evacuación. La app no confirma refugios ni recorridos habilitados; consultalos con la autoridad local.")
    with st.expander("Ver evidencia y fuentes de las recomendaciones"):
        st.write("**Estado original de la evaluación:** " + resumen["estado_regional"])
        for motivo in resumen["motivos"]:
            st.write("• " + motivo)
        for etiqueta, url in FUENTES_ACCIONES:
            st.link_button(etiqueta, url)
        st.link_button("Zárate · contactos municipales", "https://zarate.gob.ar/telefonos-utiles/")
        st.link_button("Campana · contactos municipales", "https://www.campana.gob.ar/telefonos-utiles/")


def hover_meteorologico_zc(row, referencia=None):
    """Rótulos de mapa con unidades; el mapa mantiene su alcance meteorológico."""
    def esc(valor):
        return html.escape(_texto(valor))
    ref = _fecha(referencia or datetime.now(timezone.utc))
    lluvia = resumir_lluvia(row, ref)
    valores = lluvia['valores']
    campos = [("Lluvia prevista · 24 h", _valor(valores.get("lluvia_futura_24"), 1, " mm")),
              ("Lluvia prevista · 72 h", _valor(valores.get("lluvia_futura_72"), 1, " mm")),
              ("Suelo · agua por volumen", _valor(valores.get("humedad_suelo_promedio"), 3, " m³/m³"))]
    return "<b>"+esc(row.get("localidad"))+"</b><br>Semáforo meteorológico: "+esc(lluvia['nivel'])+"<br>"+"<br>".join(esc(k)+": "+esc(v) for k,v in campos)+"<br>Cálculo: "+esc(row.get("actualizado") or "Sin fecha")+"<br>Río y preparación regional: consultar la ficha superior."
