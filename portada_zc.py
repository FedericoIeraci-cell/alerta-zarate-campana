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
                f"Puerto de {partido} (INA {serie}): altura actual o referencia de la misma escala por confirmar."}


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


def _causas_publicas(motivos, senales):
    """Una explicación por evidencia; conserva todos los disparadores críticos.

    El título técnico de una señal no constituye otra causa. Sólo se agrupan
    señales cuyos motivos, mecanismo y fechas publicadas son idénticos.
    """
    def sin_prefijo(texto):
        return re.sub(r"^Prevención local:\s*", "", _texto(texto))

    actuales_modelo = [_texto(m) for a in senales if a.get('mecanismo') == 'Evidencia actual de río / parte local'
                       for m in (a.get('motivos') or []) if _texto(m)]
    criticos = [m for m in motivos + actuales_modelo if any(t in _normal(m) for t in
                ("altura observada alcanza", "agua reportada", "acceso reportado cerrado", "nivel experimental rojo"))]
    salida = []
    cubiertos = set()
    for causa in criticos:
        original = sin_prefijo(causa)
        # El modelo puede repetir el mismo parte actual con otro encabezado.
        if causa.startswith("Modelo local · ") and ": " in causa:
            original = causa.split(": ", 1)[1]
        clave = _normal(original)
        if clave in cubiertos:
            continue
        cubiertos.add(clave)
        etiqueta = ("Río observado" if "altura observada alcanza" in clave else
                    "Parte local" if any(t in clave for t in ("agua reportada", "acceso reportado cerrado")) else
                    "Meteorología modelada")
        salida.append(etiqueta + " · " + original)

    grupos = {}
    motivos_modelo = set()
    hay_smn_modelo = False
    for senal in senales:
        mecanismo = _texto(senal.get("mecanismo"))
        hechos = tuple(_texto(m) for m in (senal.get("motivos") or []) if _texto(m))
        localidad = _texto(senal.get("localidad")) or "Sector local"
        horizonte = _texto(senal.get("horizonte") or senal.get("id_horizonte") or "plazo por confirmar")
        for hecho in hechos:
            motivos_modelo.add(_normal("Modelo local · " + localidad + " · " + horizonte + ": " + hecho))
        if mecanismo == "Evidencia actual de río / parte local":
            # Ya se muestran sus cruces y partes, con su localidad original.
            continue
        inicio, fin = _fecha(senal.get("inicio")), _fecha(senal.get("fin"))
        clave = (mecanismo, hechos, inicio, fin, horizonte)
        if clave not in grupos:
            grupos[clave] = []
        if localidad not in grupos[clave]:
            grupos[clave].append(localidad)
        hay_smn_modelo = hay_smn_modelo or mecanismo == "Aviso oficial SMN"
    etiquetas = {"Tendencia del pronóstico fluvial": "Previsión del río",
                 "Aviso oficial SMN": "Aviso oficial SMN",
                 "Lluvia prevista": "Lluvia prevista por el modelo",
                 "Lluvia + suelo/escurrimiento": "Lluvia, suelo y escurrimiento modelados",
                 "Lluvia prevista + río actualmente alto": "Lluvia prevista y río observado alto"}
    for (mecanismo, hechos, inicio, fin, horizonte), localidades in grupos.items():
        etiqueta = etiquetas.get(mecanismo, "Previsión local")
        lugar = ", ".join(localidades).replace(" · estación de referencia", "")
        hecho = " ".join(hechos) or "La evaluación indica una señal preventiva; revisá su evidencia completa."
        hecho = hecho.replace("Ascenso máximo desde el primer valor futuro de la misma serie:",
                              "Subida prevista desde el primer dato del pronóstico:")
        periodo = (" Período publicado: " + _hora(inicio) + " a " + _hora(fin) + "."
                   if inicio is not None and fin is not None else " Plazo: " + horizonte + ".")
        salida.append(etiqueta + " · " + lugar + ": " + hecho + periodo)
    secundarios = []
    for motivo in motivos:
        if motivo in criticos or _normal(motivo) in motivos_modelo:
            continue
        original = sin_prefijo(motivo)
        clave = _normal(original)
        if clave in cubiertos or (hay_smn_modelo and "smn:" in clave):
            continue
        if not any(t in clave for t in ("smn:", "modelo local", "aguas altas", "tendencia ascendente")):
            continue
        cubiertos.add(clave)
        if "aguas altas" in clave or "tendencia ascendente" in clave:
            original = "Contexto de cuenca · " + original
        secundarios.append(original)
    salida.extend(secundarios[:2])
    return list(dict.fromkeys(salida)) or [sin_prefijo(m) for m in motivos[:2]] or ["Faltan datos verificados para describir la situación regional."]


def construir_portada_zc(row, decision=None, modelo=None, rio=None, cap=None, cuenca=None, referencia=None,
                        observacion_automatica=None):
    """Reutiliza la prioridad regional y muestra la evidencia propia del punto elegido."""
    referencia = _fecha(referencia or datetime.now(timezone.utc))
    if referencia is None:
        raise ValueError("La portada necesita una referencia con zona horaria.")
    row = dict(row)
    decision = decision if isinstance(decision, dict) else {}
    modelo = modelo if isinstance(modelo, dict) else {}
    lluvia = resumir_lluvia(row, referencia)
    rio = resumir_rio(row.get("partido", ""), rio, modelo.get("rios") or [], referencia)
    automatica = None
    if row.get('partido') == 'Zárate' and isinstance(observacion_automatica,dict):
        from hidrometria_local import revalidar_altura_zarate
        automatica = revalidar_altura_zarate(observacion_automatica,referencia)
    represa = resumir_represa(cuenca, referencia)
    smn = resumir_smn(row, cap, referencia)
    prioridad = decision.get("prioridad")
    if type(prioridad).__name__ in ("bool", "bool_") or prioridad not in (0, 1, 2):
        prioridad = None
    motivos = [_texto(m) for m in (decision.get("motivos") or []) if _texto(m)]
    senales = [a for a in (modelo.get('alertas') or []) if isinstance(a,dict)
               and a.get('prioridad') == prioridad and prioridad in (1,2)]
    causas = _causas_publicas(motivos, senales)
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
            "lluvia": lluvia, "rio": rio, "observacion_automatica": automatica, "represa": represa, "smn": smn,
            "faltantes": list(dict.fromkeys(faltantes)), "incertidumbres": dudas,
            "senales": senales,
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


def html_resumen_portada_zc(resumen):
    """Primera lectura responsiva: causas, cifras fechadas y una acción concreta."""
    def esc(valor):
        return html.escape(str(valor), quote=True)
    def enlace(titulo, url):
        return '<a href="'+esc(url)+'" target="_blank" rel="noopener noreferrer">'+esc(titulo)+'</a>'
    ref = resumen["referencia"]
    lluvia, rio, represa, smn = (resumen[k] for k in ("lluvia", "rio", "represa", "smn"))
    automatica = resumen.get('observacion_automatica') or {}
    etiquetas = {2: "Atención preventiva alta", 1: "Preparar medidas", 0: "Mantener seguimiento", None: "Información por confirmar"}
    colores = {2: "#a34113", 1: "#8b6209", 0: "#175b83", None: "#536576"}
    acciones = {2: "Confirmá ahora con Defensa Civil los sectores afectados, los accesos y la asistencia necesaria.",
                1: "Revisá los avisos y prepará comunicación y accesos antes de salir o trabajar.",
                0: "Seguí las nuevas lecturas y los avisos; verificá las condiciones antes de circular.",
                None: "Confirmá las fuentes que faltan antes de decidir una salida o una tarea."}
    causas = '<ul class="zc-portada-causas">'+''.join('<li>'+esc(c)+'</li>' for c in resumen['causas'])+'</ul>'
    cifras = []
    for campo, titulo, clave in (("lluvia_futura_24", "Lluvia prevista · 24 h", "lluvia24"),
                                ("lluvia_futura_72", "Lluvia prevista · 72 h", "lluvia72")):
        fecha = ("Desde " if lluvia['vigente'] else "Referencia sin vigencia: ")+_hora(lluvia['referencia'])
        cifras.append('<article class="zc-portada-cifra" data-cifra="'+clave+'"><h3>'+esc(titulo)+'</h3>'
                      '<p class="zc-portada-valor">'+esc(_valor(lluvia['valores'][campo],1,' mm'))+'</p>'
                      '<p class="zc-portada-fecha">'+esc(fecha)+'</p><p class="zc-portada-fuente">'
                      +enlace('ECMWF / Open-Meteo',lluvia['fuente'])+'</p></article>')
    automatica_actual = automatica.get('vigente') is True and _numero(automatica.get('altura_m')) is not None
    nombre_rio = automatica['nombre'] if automatica_actual else rio['estacion']
    valor_rio = automatica['altura_m'] if automatica_actual else rio['altura']
    fecha_rio = ("Lectura: " + _hora(_fecha(automatica.get('fecha_observada')))) if automatica_actual else (
                ("Lectura: " if rio['vigente'] else "Último registro disponible: ")+_hora(rio['fecha']))
    fuente_rio = automatica['fuente'] if automatica_actual else rio['fuente'] or 'https://alerta.ina.gob.ar/'
    etiqueta_fuente = 'INA · RHN-SAT · serie 29437' if automatica_actual else 'INA · serie '+str(rio['serie'])
    nota_rio = ('Medición automática RHN-SAT. No se compara con los umbrales del puerto INA 40 ni reduce la preparación regional.'
                if automatica_actual else rio['estado']+'; es una escala del puerto, no profundidad en una calle o vivienda.')
    cifras.append('<article class="zc-portada-cifra zc-portada-cifra-rio" data-cifra="rio"><h3>Río observado · '
                  +esc(nombre_rio)+'</h3><p class="zc-portada-valor">'+esc(_valor(valor_rio,2,' m'))
                  +'</p><p class="zc-portada-fecha">'+esc(fecha_rio)+'</p><p class="zc-portada-fuente">'
                  +enlace(etiqueta_fuente,fuente_rio)+'</p></article>')
    nota_lluvia = ("Lluvia de modelo, contada desde la referencia indicada; la emisión de la corrida no está informada."
                   if lluvia['completo'] else lluvia['faltante'])
    dia = represa['fecha_documento']
    rep_fecha = dia.strftime('%d/%m/%Y')+' · sin hora publicada' if dia else 'Fecha sin confirmar'
    rep_valor = (' Aporte previsto: '+_valor(represa['afluencia_prevista'],0,' m³/s')+'.'
                 if represa['afluencia_prevista'] is not None else '')
    smn_pendiente = '<p>'+esc(smn['faltante'])+'</p>' if smn['faltante'] else ''
    color = colores[resumen['prioridad']]
    return f'''<style>
.zc-portada{{font-family:system-ui,sans-serif;color:#183448;background:#fff;border:1px solid #dce5ed;border-top:4px solid {color};border-radius:12px;padding:16px 18px;margin:2px 0 12px}}
.zc-portada *{{box-sizing:border-box}}.zc-portada h2{{font-size:23px;line-height:1.2;margin:0 0 5px;padding:0;color:{color}}}.zc-portada h3{{font-size:14px;line-height:1.35;margin:0 0 5px;padding:0}}
.zc-portada p,.zc-portada li{{font-size:14px;line-height:1.45;margin:4px 0;overflow-wrap:anywhere}}.zc-portada .zc-portada-meta,.zc-portada .zc-portada-fecha,.zc-portada .zc-portada-fuente,.zc-portada .zc-portada-nota{{font-size:12px;color:#506477}}
.zc-portada-causas{{margin:9px 0 12px;padding-left:18px}}.zc-portada-causas li{{margin:4px 0}}.zc-portada-cifras{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}}
.zc-portada-cifra{{background:#f4f8fb;border:1px solid #dfe7ee;border-radius:9px;padding:11px 12px;min-width:0}}.zc-portada .zc-portada-valor{{font-size:28px;line-height:1.15;font-weight:800;margin:6px 0 8px;letter-spacing:-.02em}}
.zc-portada a{{color:#075985;text-decoration:underline}}.zc-portada-ahora{{border-left:3px solid {color};padding:3px 0 3px 10px;margin:12px 0}}.zc-portada-contexto{{display:grid;grid-template-columns:1fr 1fr;gap:12px;border-top:1px solid #dce5ed;padding-top:11px;margin-top:12px}}
@media(max-width:620px){{.zc-portada{{padding:12px;border-radius:10px}}.zc-portada h2{{font-size:21px}}.zc-portada-cifras{{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}}.zc-portada-cifra{{padding:9px}}.zc-portada-cifra-rio{{grid-column:1/-1}}.zc-portada .zc-portada-valor{{font-size:25px}}.zc-portada-contexto{{grid-template-columns:1fr;gap:10px}}}}
</style><section class="zc-portada" aria-label="Resumen de {esc(resumen['localidad'])}">
<h2>{esc(etiquetas[resumen['prioridad']])}</h2><p class="zc-portada-meta"><strong>{esc(resumen['localidad'])}</strong> · {esc(resumen['alcance_estado'])} · evaluación: {esc(_hora(resumen['fecha_evaluacion'],ref))}</p>
{causas}<div class="zc-portada-cifras">{''.join(cifras)}</div>
<p class="zc-portada-nota">{esc(nota_lluvia)} Río: {esc(nota_rio)}</p>
<div class="zc-portada-ahora"><p><strong>Qué hacer ahora:</strong> {esc(acciones[resumen['prioridad']])} No cruces agua.</p></div>
<div class="zc-portada-contexto"><article><h3>Avisos oficiales SMN</h3><p>{esc(smn['estado'])}</p>{smn_pendiente}<p class="zc-portada-fecha">Listado: {esc(_hora(smn['fecha']))} · {enlace('SMN',smn['fuente'])}</p></article>
<article><h3>Represas · contexto aguas arriba</h3><p>{esc(represa['estado']+rep_valor)}</p><p class="zc-portada-fecha">Parte: {esc(rep_fecha)} · {enlace('Yacyretá',represa['fuente'])}</p><p class="zc-portada-nota">No indica altura ni hora de llegada del agua a esta referencia.</p></article></div>
<p class="zc-portada-nota">La preparación abarca los sectores mencionados. La lluvia baja no descarta una crecida y esta orientación no es una orden de evacuación.</p></section>'''


def mostrar_portada_zc(st, resumen):
    ref = resumen["referencia"]
    st.markdown(html_resumen_portada_zc(resumen), unsafe_allow_html=True)
    publico = st.radio("Más acciones para", ["Mi hogar / mi comunidad", "Productor / trabajo rural"],
                       horizontal=True, key="zc_portada_publico")
    acciones = acciones_portada_zc(resumen["prioridad"], publico)
    st.write("**Prepará:** " + acciones[0])
    with st.expander("Plan de preparación y contactos oficiales"):
        for accion in acciones[1:]:
            st.write("• " + accion)
        st.caption("Si hay agua creciente o peligro: no cruces agua y pedí asistencia. Seguí las indicaciones de la autoridad local para resguardo o evacuación.")
        st.caption("La app no confirma refugios ni recorridos habilitados; consultalos con la autoridad local.")
        for etiqueta, url in FUENTES_ACCIONES:
            st.link_button(etiqueta, url)
        st.link_button("Zárate · contactos municipales", "https://zarate.gob.ar/telefonos-utiles/")
        st.link_button("Campana · contactos municipales", "https://www.campana.gob.ar/telefonos-utiles/")

    lluvia, rio, represa, smn = (resumen[k] for k in ("lluvia", "rio", "represa", "smn"))
    with st.expander("Lluvia · períodos, cálculo y fuente"):
        st.write(lluvia["estado"])
        st.write("**Próximos 7 días:** " + _valor(lluvia["valores"]["lluvia_futura_7d"], 1, " mm"))
        st.write("**Índice meteorológico:** " + lluvia["nivel"] + " · " + _valor(lluvia["indice"], 1, "/100"))
        st.caption("Acumulados desde: " + _hora(lluvia['referencia']) + ". Las ventanas de 24 y 72 horas parten de esta referencia.")
        st.caption("Cálculo meteorológico: " + _hora(lluvia['fecha'],ref) + ". Consulta: " + _hora(lluvia["consulta"], ref) + ". La API no informa la emisión de la corrida. Lluvia estimada por el modelo, no medición local.")
        st.link_button("Fuente meteorológica · Open-Meteo", lluvia["fuente"], key="zc_portada_lluvia")
    with st.expander("Río · umbrales, pronóstico y fuente"):
        automatica = resumen.get('observacion_automatica') or {}
        if automatica and _numero(automatica.get('altura_m')) is not None and _fecha(automatica.get('fecha_observada')) is not None:
            st.write('**Estación automática: '+_texto(automatica.get('nombre'))+' · serie 29437**')
            etiqueta = 'Lectura vigente' if automatica.get('vigente') is True else 'Antecedente sin vigencia confirmada'
            st.write(etiqueta+': '+_valor(automatica.get('altura_m'),2,' m')+' · '+_hora(_fecha(automatica.get('fecha_observada'))))
            if automatica.get('coincidencia_documental_pronostico') is True:
                st.caption('La serie automática 29437 y el pronóstico 29534 comparten estación, unidad y cero publicados por INA. Esto no vincula los umbrales del puerto INA 40 a esa escala ni confirma una inundación.')
            else:
                st.caption('La vinculación documental de esta lectura con la serie de pronóstico requiere confirmación.')
            st.caption('La lectura automática no modifica la prioridad regional ni se usa para dar por seguros accesos o viviendas.')
            if automatica.get('fuente'):
                st.link_button('Fuente automática · INA 29437',automatica['fuente'],key='zc_portada_rio_automatico')
        elif automatica:
            st.caption('Estación automática RHN-SAT de Zárate: no se dispone de una lectura verificada.')
        st.write('**Puerto de '+rio['estacion']+' · serie observada INA '+str(rio['serie'])+'**')
        st.write(rio["estado"])
        st.write('Altura vigente del puerto: '+_valor(rio['altura'],2,' m'))
        st.caption("Registro: " + _hora(rio["fecha"], ref) + " · serie observada INA " + str(rio["serie"]))
        for campo, titulo in (("alerta", "alerta"), ("evacuacion", "evacuación")):
            st.write("Referencia de " + titulo + ": **" + _valor(rio[campo], 2, " m") + "** en la misma escala observada.")
        if rio["pronostico_vigente"]:
            st.caption("Pronóstico INA emitido " + _hora(rio['emision_pronostico']) + " y disponible hasta " + _hora(rio["fin_pronostico"]) +
                       ". Sus valores no se comparan con los umbrales de la escala observada del puerto; se revisa en Suelo y ríos.")
        else:
            st.caption("Pronóstico local del río: actualidad por confirmar.")
        st.caption("Altura de la escala del puerto; no es profundidad en una calle o vivienda. Alcanzar una referencia de evacuación no equivale a una orden oficial.")
        st.link_button("Fuente del río · INA", rio["fuente"] or "https://alerta.ina.gob.ar/", key="zc_portada_rio")
    with st.expander("SMN · avisos, áreas y fechas"):
        st.write(smn["estado"])
        if smn['faltante']:
            st.write(smn['faltante'])
        st.caption("Publicación del canal: " + _hora(smn["fecha"], ref))
        for i, aviso in enumerate(smn["avisos"]):
            st.write("**" + aviso["estado"] + " · " + aviso["fenomeno"] + "**")
            st.caption(_hora(aviso["inicio"]) + " a " + _hora(aviso["fin"]) + ". Emisión: " + _hora(aviso['emision']))
            st.link_button("Abrir aviso oficial", aviso["fuente"], key="zc_portada_smn_"+str(i))
        st.caption("La coincidencia corresponde al punto o al partido mencionado; revisá el área exacta del aviso.")
        st.link_button("Todos los avisos · SMN", smn["fuente"], key="zc_portada_smn")
    with st.expander("Represas · parte original y alcance"):
        st.write(represa["estado"])
        dia = represa["fecha_documento"]
        st.caption("Fecha del parte: " + (dia.strftime("%d/%m/%Y") if dia else "Sin confirmar") + " · fecha documental, sin hora de medición.")
        if represa["afluencia_prevista"] is not None:
            st.write("**Aporte previsto a Yacyretá:** " + _valor(represa["afluencia_prevista"], 0, " m³/s"))
            st.caption("Día de la previsión: " + _texto(represa["fecha_afluencia"]) + ". No es descarga total ni altura local.")
        st.caption("Este contexto ayuda a seguir la cuenca. No permite calcular la hora de llegada de una crecida a tu zona.")
        st.link_button("Parte original · Yacyretá", represa["fuente"], key="zc_portada_represa")
    if resumen["faltantes"]:
        with st.expander("Información que falta confirmar · " + str(len(resumen['faltantes'])) + " puntos"):
            for falta in resumen["faltantes"]:
                st.write("• " + falta)
            for duda in resumen['incertidumbres']:
                st.write("• " + duda)
    with st.expander("Evaluación completa · causas y límites"):
        st.write("**Estado original de la evaluación:** " + resumen["estado_regional"])
        for motivo in resumen["motivos"]:
            st.write("• " + motivo)
        for senal in resumen.get('senales',[]):
            st.write("**" + _texto(senal.get('localidad')) + " · " + _texto(senal.get('nivel')) + "**")
            st.caption("Ventana publicada: " + _hora(_fecha(senal.get('inicio'))) + " a " + _hora(_fecha(senal.get('fin'))) + ". No indica una hora de inundación.")
            for limite in senal.get('incertidumbres') or []:
                st.write("• " + _texto(limite))
            for fuente in senal.get('fuentes') or []:
                enlace = _url(fuente, {'alerta.ina.gob.ar','alerta.ina.gov.ar','www.ina.gob.ar','www.ina.gov.ar',
                                      'api.open-meteo.com','open-meteo.com','ssl.smn.gob.ar','smn.gob.ar','www.smn.gob.ar'})
                if enlace:
                    st.markdown('[Fuente original de la señal]('+enlace+')')


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
