"""Recupera grillas públicas fechadas cuando falla la consulta local.

No calcula riesgos, no completa variables ausentes ni renueva la fecha de una
consulta. La captura compartida conserva la celda y las unidades de su fuente.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from zoneinfo import ZoneInfo

ART = ZoneInfo("America/Argentina/Buenos_Aires")
FUENTE = "https://api.open-meteo.com/v1/ecmwf"
MAX_AGE_HOURS = 3
ERROR_PUBLICO = "La fuente meteorológica no devolvió datos utilizables para este nodo."
_CAPAS_SUELO = ("soil_moisture_0_to_7cm", "soil_moisture_7_to_28cm",
                "soil_moisture_28_to_100cm", "soil_moisture_100_to_255cm")


def _fecha(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _numero(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return value if math.isfinite(value) else None


def _grilla_utilizable(nodo, payload, consulta, referencia, *, exigir_valor=False):
    if not isinstance(payload, dict) or payload.get("error"):
        return False
    fecha = _fecha(consulta)
    if fecha is None or not -300 <= (referencia - fecha).total_seconds() <= MAX_AGE_HOURS * 3600:
        return False
    lat, lon = _numero(payload.get("latitude")), _numero(payload.get("longitude"))
    nlat, nlon = _numero(nodo.get("lat")), _numero(nodo.get("lon"))
    if None in (lat, lon, nlat, nlon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    p1, p2 = math.radians(nlat), math.radians(lat)
    dp, dl = math.radians(lat - nlat), math.radians(lon - nlon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    if 6371 * 2 * math.asin(math.sqrt(min(1, max(0, h)))) > 40:
        return False
    if (payload.get("timezone") not in {"America/Argentina/Buenos_Aires", "America/Buenos_Aires"}
            or payload.get("utc_offset_seconds") != -10800):
        return False
    hourly, units = payload.get("hourly"), payload.get("hourly_units")
    if not isinstance(hourly, dict) or not isinstance(units, dict):
        return False
    times, rain = hourly.get("time"), hourly.get("precipitation")
    if (units.get("time") != "iso8601" or units.get("precipitation") != "mm"
            or not isinstance(times, list) or not 1 <= len(times) <= 800
            or not isinstance(rain, list) or len(rain) != len(times)):
        return False
    parsed = []
    aware = None
    try:
        for value in times:
            dt = datetime.fromisoformat(value)
            is_aware = dt.tzinfo is not None and dt.utcoffset() is not None
            if aware is not None and aware != is_aware:
                return False
            aware = is_aware
            dt = dt.astimezone(ART) if is_aware else dt.replace(tzinfo=ART)
            if dt.minute or dt.second or dt.microsecond:
                return False
            parsed.append(dt)
    except (ValueError, TypeError):
        return False
    if any(b - a != timedelta(hours=1) for a, b in zip(parsed, parsed[1:])):
        return False
    values = [_numero(value) for value in rain]
    # Un valor inválido del horizonte extendido no invalida lluvia y suelo
    # utilizables en las ventanas del índice. Cada horizonte vuelve a validar
    # sus propios valores; el original se conserva y nunca se convierte en cero.
    corte = referencia.astimezone(ART).replace(minute=0, second=0, microsecond=0)
    if any(value is not None and not 0 <= value <= 1000
           for hora, value in zip(parsed, values)
           if corte - timedelta(hours=168) < hora <= corte + timedelta(hours=72)):
        return False
    if any(value is not None and (_numero(value) is None) for value in rain):
        return False
    return not exigir_valor or any(value is not None for value in values)


def _leer_red(datos_red, referencia):
    from red_integrada import consultar_red_integrada, validar_red_integrada
    try:
        datos = consultar_red_integrada(referencia=referencia) if datos_red is None else datos_red
        if not isinstance(datos, dict) or datos.get("error"):
            return None
        datos = validar_red_integrada(datos, referencia=referencia)
        return datos if datos.get("snapshot_vigente") is True else None
    except (ValueError, TypeError, KeyError, OverflowError):
        return None


def _respuesta_completa(nodo, payload, consulta, referencia):
    """Cobertura que necesita el índice, sin calcular ni asignar riesgo."""
    if not _grilla_utilizable(nodo, payload, consulta, referencia):
        return False
    hourly, units = payload["hourly"], payload["hourly_units"]
    horas = []
    for value in hourly["time"]:
        hora = datetime.fromisoformat(value)
        horas.append(hora.astimezone(ART) if hora.tzinfo is not None else hora.replace(tzinfo=ART))
    ref = referencia.astimezone(ART).replace(minute=0, second=0, microsecond=0)
    posiciones = {hora: i for i, hora in enumerate(horas)}

    def ventana(campo, cantidad, futura=False):
        values = hourly.get(campo)
        if units.get(campo) != "mm" or not isinstance(values, list) or len(values) != len(horas):
            return False
        inicio = ref if futura else ref - timedelta(hours=cantidad)
        for n in range(1, cantidad + 1):
            i = posiciones.get(inicio + timedelta(hours=n))
            value = _numero(values[i]) if i is not None else None
            if value is None or not 0 <= value <= 1000:
                return False
        return True

    if not (ventana("precipitation", 168) and ventana("precipitation", 72, True)
            and ventana("runoff", 72)):
        return False
    capas = 0
    for campo in _CAPAS_SUELO:
        values = hourly.get(campo)
        if (units.get(campo) not in {"m³/m³", "m3/m3"} or
                not isinstance(values, list) or len(values) != len(horas)):
            continue
        if any(0 <= (ref - hora).total_seconds() <= 3 * 3600
               and (value := _numero(values[i])) is not None and 0 <= value <= 1
               for i, hora in enumerate(horas)):
            capas += 1
    return capas >= 3


def _leer_captura_completa(nodos, referencia, contenido=None):
    """Contrato comprimido compartido con el productor; falla de forma aislada."""
    if contenido is False:
        return None  # El getter ya hizo su única consulta de la captura.
    try:
        from meteorologia_compartida import consultar_captura_zc, deserializar_captura
        return (consultar_captura_zc(nodos, referencia=referencia) if contenido is None
                else deserializar_captura(contenido, nodos, referencia=referencia))
    except Exception:
        return None


def _respuesta_de_captura(dato, consulta, referencia):
    recuperado = deepcopy(dato)
    recuperado["_consulta_meteorologica"] = _fecha(consulta).astimezone(ART).isoformat()
    recuperado["_origen_meteorologico"] = "captura_ecmwf_zc"
    recuperado["_recuperacion_meteorologica"] = "captura_completa_compartida_vigente"
    recuperado["_fecha_ultimo_intento_meteorologico"] = referencia.isoformat()
    return recuperado


def obtener_respuestas_completas_zc(nodos, referencia=None):
    """Primera opción rápida del getter: captura pública completa o ``None``.

    Sólo evita las consultas directas si todos los puntos tienen la cobertura
    meteorológica necesaria. Si devuelve ``None``, el getter puede continuar con
    la API y pasar ``captura_completa=False`` a la recuperación final para no
    repetir la descarga que ya se intentó.
    """
    ref = _fecha(referencia) if referencia is not None else datetime.now(timezone.utc)
    if ref is None:
        return None
    nodos = list(nodos)
    captura = _leer_captura_completa(nodos, ref)
    if captura is None or not all(
            _respuesta_completa(nodo, dato, captura["consultado"], ref)
            for nodo, dato in zip(nodos, captura["datos"])):
        return None
    return [_respuesta_de_captura(dato, captura["consultado"], ref)
            for dato in captura["datos"]]


def recuperar_respuestas_zc(nodos, respuestas, referencia=None, datos_red=None,
                           captura_completa=None):
    """Mantiene respuestas utilizables y rescata únicamente las que fallaron.

    ``respuestas=[]`` permite solicitar primero la captura completa compartida y
    consultar después los puntos que sigan sin datos. Nunca convierte resúmenes
    acumulados en una serie horaria. La edad máxima sigue siendo la del contrato
    público compartido: tres horas desde la consulta original, no su lectura.
    """
    ref = _fecha(referencia) if referencia is not None else datetime.now(timezone.utc)
    if ref is None:
        raise ValueError("La recuperación necesita fecha, hora y zona horaria verificables.")
    nodos = list(nodos)
    respuestas = list(respuestas) if isinstance(respuestas, (list, tuple)) else []
    salida = []
    incompletos = []
    for i, nodo in enumerate(nodos):
        dato = deepcopy(respuestas[i]) if i < len(respuestas) and isinstance(respuestas[i], dict) else {"error": ERROR_PUBLICO}
        salida.append(dato)
        if not _respuesta_completa(nodo, dato, dato.get("_consulta_meteorologica"), ref):
            incompletos.append((i, nodo))
    if not incompletos:
        return salida
    captura = _leer_captura_completa(nodos, ref, captura_completa)
    if captura is not None:
        original = captura["consultado"]
        for i, nodo in incompletos:
            dato = captura["datos"][i]
            anterior = salida[i]
            if not _grilla_utilizable(nodo, dato, original, ref, exigir_valor=True):
                continue
            if (_grilla_utilizable(nodo, anterior, anterior.get("_consulta_meteorologica"), ref)
                    and not _respuesta_completa(nodo, dato, original, ref)):
                continue
            salida[i] = _respuesta_de_captura(dato, original, ref)
    faltantes = [(i, nodo) for i, nodo in incompletos
                 if not _grilla_utilizable(nodo, salida[i], salida[i].get("_consulta_meteorologica"), ref)]
    if not faltantes:
        return salida
    red = _leer_red(datos_red, ref)
    if red is None:
        return salida
    index = {}
    for item in red["nodos"]:
        if item.get("red") == "Zárate–Campana":
            key = (item.get("localidad"), item.get("provincia"), item.get("lat"), item.get("lon"))
            index[key] = item
    for i, nodo in faltantes:
        key = (nodo.get("localidad"), nodo.get("provincia"), nodo.get("lat"), nodo.get("lon"))
        item = index.get(key)
        if not item or item.get("fuente") != FUENTE or item.get("grilla_version") != 1:
            continue
        original = item.get("fecha_consulta")
        grilla = item.get("grilla_verificada")
        if not _grilla_utilizable(nodo, grilla, original, ref, exigir_valor=True):
            continue
        recuperado = deepcopy(grilla)
        recuperado["_consulta_meteorologica"] = _fecha(original).astimezone(ART).isoformat()
        recuperado["_origen_meteorologico"] = "red_integrada"
        recuperado["_recuperacion_meteorologica"] = "grilla_compartida_vigente"
        recuperado["_fecha_ultimo_intento_meteorologico"] = ref.isoformat()
        salida[i] = recuperado
    return salida
