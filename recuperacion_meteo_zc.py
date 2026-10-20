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
    if any(value is not None and not 0 <= value <= 1000 for value in values):
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


def recuperar_respuestas_zc(nodos, respuestas, referencia=None, datos_red=None):
    """Mantiene respuestas utilizables y rescata únicamente las que fallaron.

    ``respuestas=[]`` permite solicitar primero las grillas compartidas y
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
    faltantes = []
    for i, nodo in enumerate(nodos):
        dato = deepcopy(respuestas[i]) if i < len(respuestas) and isinstance(respuestas[i], dict) else {"error": ERROR_PUBLICO}
        salida.append(dato)
        if not _grilla_utilizable(nodo, dato, dato.get("_consulta_meteorologica"), ref):
            faltantes.append((i, nodo))
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
