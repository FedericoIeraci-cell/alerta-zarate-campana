"""Captura completa comprimida: recuperación e integración sin acceso a red."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
import math
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import meteorologia_compartida as meteo
import recuperacion_meteo_zc as recovery
import red_integrada as red
from test_recuperacion_meteo_portada import NOW, shared, weather

ROOT = Path(__file__).resolve().parents[1]


def completa(nodo):
    # Datos controlados de prueba: todos se serializan como una respuesta pública.
    raw = weather(nodo)
    hours = len(raw["hourly"]["time"])
    variables = {"runoff": (0.05, "mm"), "temperature_2m": (23.7, "°C"),
                 "wind_speed_10m": (12.0, "km/h"), "wind_gusts_10m": (20.0, "km/h"),
                 "cape": (150.0, "J/kg"), "evapotranspiration": (None, "undefined")}
    for campo in recovery._CAPAS_SUELO:
        variables[campo] = (0.30, "m³/m³")
    for campo, (valor, unidad) in variables.items():
        raw["hourly"][campo] = [valor] * hours
        raw["hourly_units"][campo] = unidad
    raw["daily"] = {"time": [(NOW.date() + timedelta(days=i)).isoformat() for i in range(15)],
                    "precipitation_sum": [0.0] * 15, "temperature_2m_max": [25.0] * 15}
    raw["daily_units"] = {"time": "iso8601", "precipitation_sum": "mm",
                          "temperature_2m_max": "°C"}
    return raw


def documento(nodos=None, consultado=None, datos=None):
    nodos = red.NODOS_ZC if nodos is None else nodos
    datos = [completa(n) for n in nodos] if datos is None else datos
    return meteo.serializar_captura(meteo.crear_captura(
        nodos, datos, consultado or NOW - timedelta(minutes=20)))


class CapturaCompletaZCTests(unittest.TestCase):
    def setUp(self):
        self.nodos = deepcopy(red.NODOS_ZC)
        self.failure = [{"error": "ReadTimeout"} for _ in self.nodos]
        bloqueo = patch("requests.sessions.Session.request", side_effect=AssertionError("HTTP real prohibido"))
        self.http = bloqueo.start()
        self.addCleanup(bloqueo.stop)

    def recuperar(self, contenido, respuestas=None, datos_red=None):
        return recovery.recuperar_respuestas_zc(
            self.nodos, self.failure if respuestas is None else respuestas, NOW,
            {"error": "Sin grilla"} if datos_red is None else datos_red,
            captura_completa=contenido)

    def test_roundtrip_recupera_diez_respuestas_completas_y_preserva_fecha_valores_nulos_y_diarios(self):
        raw = [completa(n) for n in self.nodos]
        result = self.recuperar(documento(datos=raw))
        self.assertEqual(len(result), 10)
        for original, dato in zip(raw, result):
            self.assertEqual(dato["hourly"], original["hourly"])
            self.assertEqual(dato["daily"], original["daily"])
            self.assertEqual(dato["hourly_units"], original["hourly_units"])
            self.assertEqual(dato["hourly"]["precipitation"][0], 0.0)
            self.assertIsNone(dato["hourly"]["evapotranspiration"][0])
            self.assertEqual(datetime.fromisoformat(dato["_consulta_meteorologica"]),
                             NOW - timedelta(minutes=20))
            self.assertEqual(datetime.fromisoformat(dato["_fecha_ultimo_intento_meteorologico"]), NOW)
            self.assertEqual(dato["_origen_meteorologico"], "captura_ecmwf_zc")
        self.http.assert_not_called()

    def test_respuestas_recuperadas_producen_diez_indices_completos_en_el_motor_real(self):
        spec = importlib.util.spec_from_file_location("_zc_motor_captura_completa", ROOT / "app.py")
        app = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"ALA_MONITOR_HEADLESS": "1"}):
            spec.loader.exec_module(app)
        filas = self.recuperar(documento())
        with patch.object(app, "ahora", return_value=NOW):
            result = [app.procesar_nodo(n, d, referencia_historica=NOW) for n, d in zip(app.NODOS, filas)]
        self.assertEqual(len(result), 10)
        for fila in result:
            self.assertEqual(fila["estado_datos"], "OK", fila["error_datos"])
            self.assertTrue(fila["cobertura_meteorologica"])
            self.assertEqual(fila["lluvia_futura_72"], 0.0)
            self.assertEqual(fila["humedad_suelo_promedio"], 0.3)
            self.assertEqual(fila["temperatura"], 23.7)
            self.assertEqual(fila["capas_humedad_vigentes"], 4)
        self.http.assert_not_called()

    def test_lluvia_invalida_en_dia_13_no_descarta_corto_plazo_ni_renueva_consulta(self):
        raw = [completa(n) for n in self.nodos]
        hora = (NOW + timedelta(days=12)).replace(tzinfo=None).isoformat()
        for dato in raw:
            i = dato["hourly"]["time"].index(hora)
            dato["hourly"]["precipitation"][i] = -0.3
        original = deepcopy(raw)
        captura = meteo.deserializar_captura(documento(datos=raw), self.nodos, NOW)
        with patch.object(meteo, "consultar_captura_zc", return_value=captura):
            recuperadas = recovery.obtener_respuestas_completas_zc(self.nodos, NOW)
        self.assertEqual(len(recuperadas), 10)
        spec = importlib.util.spec_from_file_location("_zc_horizonte_invalido", ROOT / "app.py")
        app = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"ALA_MONITOR_HEADLESS": "1"}):
            spec.loader.exec_module(app)
        with patch.object(app, "ahora", return_value=NOW):
            fila = app.procesar_nodo(app.NODOS[0], recuperadas[0], referencia_historica=NOW)
        self.assertEqual(fila["estado_datos"], "OK")
        self.assertEqual(fila["lluvia_futura_72"], 0.0)
        self.assertTrue(any("precipitation" in p for p in fila["problemas_variables_meteorologicas"]))
        self.assertEqual(raw, original)
        self.assertEqual(recuperadas[0]["hourly"]["precipitation"], raw[0]["hourly"]["precipitation"])
        self.http.assert_not_called()

    def test_lluvia_invalida_en_72h_no_se_suma_como_cero_ni_acredita_indice(self):
        dato = completa(self.nodos[0])
        i = dato["hourly"]["time"].index((NOW + timedelta(hours=1)).replace(tzinfo=None).isoformat())
        for invalido in (-0.3, 1001.0):
            dato["hourly"]["precipitation"][i] = invalido
            self.assertFalse(recovery._respuesta_completa(self.nodos[0], dato, NOW, NOW))
            spec = importlib.util.spec_from_file_location("_zc_corto_invalido", ROOT / "app.py")
            app = importlib.util.module_from_spec(spec)
            with patch.dict(os.environ, {"ALA_MONITOR_HEADLESS": "1"}):
                spec.loader.exec_module(app)
            with patch.object(app, "ahora", return_value=NOW):
                fila = app.procesar_nodo(app.NODOS[0], dato, referencia_historica=NOW)
            self.assertEqual(fila["estado_datos"], "INCOMPLETO")
            self.assertTrue(math.isnan(fila["indice"]))
            self.assertTrue(math.isnan(fila["lluvia_futura_72"]))

    def test_mejora_respuesta_parcial_sin_reemplazar_una_directa_completa(self):
        primary = [dict(weather(n), _consulta_meteorologica=NOW.isoformat()) for n in self.nodos]
        primary[0] = dict(completa(self.nodos[0]), _consulta_meteorologica=NOW.isoformat())
        original = deepcopy(primary)
        result = self.recuperar(documento(), primary)
        self.assertEqual(result[0], primary[0])
        self.assertEqual(result[1]["hourly"]["temperature_2m"][0], 23.7)
        self.assertEqual(result[1]["_origen_meteorologico"], "captura_ecmwf_zc")
        self.assertEqual(primary, original)

    def test_si_todas_las_directas_son_completas_no_consulta_ningun_respaldo(self):
        primary = [dict(completa(n), _consulta_meteorologica=NOW.isoformat()) for n in self.nodos]
        with patch.object(recovery, "_leer_captura_completa", side_effect=AssertionError("No hace falta")), \
                patch.object(recovery, "_leer_red", side_effect=AssertionError("No hace falta")):
            self.assertEqual(self.recuperar(None, primary), primary)

    def test_captura_caduca_o_corrupta_conserva_el_respaldo_actual_de_grillas(self):
        for contenido in (documento(consultado=NOW - timedelta(hours=4)), b"{}"):
            with self.subTest(contenido=contenido[:30]):
                result = self.recuperar(contenido, datos_red=shared())
                self.assertEqual(len(result), 10)
                self.assertTrue(all(x["_origen_meteorologico"] == "red_integrada" for x in result))
                self.assertTrue(all(x["hourly"]["precipitation"][0] == 0 for x in result))
                self.assertTrue(all(x["hourly"]["runoff"][0] is None for x in result))

    def test_firma_catalogo_cantidad_orden_y_coordenadas_son_exactas(self):
        catalogos = [self.nodos[::-1], self.nodos[:9]]
        for campo, value in (("lat", -34.5), ("lon", -59.5), ("localidad", "Otro"), ("provincia", "Otra")):
            mod = deepcopy(self.nodos)
            mod[0][campo] = value
            catalogos.append(mod)
        for nodos in catalogos:
            with self.subTest(nodos=nodos):
                self.assertEqual(self.recuperar(documento(nodos=nodos)), self.failure)

    def test_celda_lejana_unidad_incorrecta_y_zona_invalida_no_contaminan_los_otros_nueve(self):
        for cambio in ("celda", "unidad", "zona"):
            raw = [completa(n) for n in self.nodos]
            if cambio == "celda": raw[-1]["latitude"] = 0.0
            if cambio == "unidad": raw[-1]["hourly_units"]["precipitation"] = "°C"
            if cambio == "zona": raw[-1]["utc_offset_seconds"] = 0
            with self.subTest(cambio=cambio):
                if cambio == "zona":
                    with self.assertRaises(meteo.CapturaMeteorologicaError):
                        documento(datos=raw)
                    continue
                result = self.recuperar(documento(datos=raw))
                self.assertEqual(result[-1], self.failure[-1])
                self.assertEqual(sum(x.get("_origen_meteorologico") == "captura_ecmwf_zc" for x in result), 9)

    def test_helper_temprano_retorna_solo_capturas_completas_sin_repetir_descarga(self):
        captura = meteo.deserializar_captura(documento(), self.nodos, NOW)
        with patch.object(meteo, "consultar_captura_zc", return_value=captura) as consultar:
            result = recovery.obtener_respuestas_completas_zc(self.nodos, NOW)
        self.assertEqual(len(result), 10)
        consultar.assert_called_once()
        self.assertEqual(result[0]["hourly"], completa(self.nodos[0])["hourly"])
        parcial = meteo.deserializar_captura(documento(datos=[weather(n) for n in self.nodos]), self.nodos, NOW)
        with patch.object(meteo, "consultar_captura_zc", return_value=parcial):
            self.assertIsNone(recovery.obtener_respuestas_completas_zc(self.nodos, NOW))
        with patch.object(meteo, "consultar_captura_zc", side_effect=AssertionError("No repetir lectura")) as consultar:
            fallback = self.recuperar(False, datos_red=shared())
        consultar.assert_not_called()
        self.assertTrue(all(x["_origen_meteorologico"] == "red_integrada" for x in fallback))

    def test_fallo_lector_completo_conserva_fallback_y_no_divulga_error_privado(self):
        with patch.object(meteo, "consultar_captura_zc", side_effect=RuntimeError("privado")):
            self.assertIsNone(recovery.obtener_respuestas_completas_zc(self.nodos, NOW))
            result = self.recuperar(None, datos_red=shared())
        self.assertTrue(all(x["_origen_meteorologico"] == "red_integrada" for x in result))
        self.assertNotIn("privado", str(result))

    def test_getter_real_lee_una_captura_comprimida_y_evitar_consultas_directas(self):
        spec = importlib.util.spec_from_file_location("_zc_getter_captura_completa", ROOT / "app.py")
        app = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"ALA_MONITOR_HEADLESS": "1"}):
            spec.loader.exec_module(app)
        body = documento()
        response = Mock(status_code=200, url=meteo.SNAPSHOT_ZC_URL,
                        headers={"Content-Length": str(len(body))})
        response.iter_content.return_value = [body[:100], body[100:]]
        session = Mock()
        session.get.return_value = response
        with patch.object(app, "ahora", return_value=NOW), \
                patch("requests.Session", return_value=session), \
                patch.object(app.requests, "get", side_effect=AssertionError("No consultar ECMWF directo")) as directo:
            result = app.obtener_datos_ecmwf()
        self.assertEqual(len(result), 10)
        self.assertEqual(result[0]["daily"]["temperature_2m_max"], [25.0] * 15)
        self.assertEqual(datetime.fromisoformat(result[0]["_consulta_meteorologica"]), NOW - timedelta(minutes=20))
        session.get.assert_called_once()
        self.assertEqual(session.get.call_args.args[0], meteo.SNAPSHOT_ZC_URL)
        directo.assert_not_called()
        response.close.assert_called_once()

    def test_getter_real_no_repite_captura_ausente_y_recupera_grillas_tras_fallo_directo(self):
        spec = importlib.util.spec_from_file_location("_zc_getter_captura_fallida", ROOT / "app.py")
        app = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"ALA_MONITOR_HEADLESS": "1"}):
            spec.loader.exec_module(app)
        with patch.object(app, "ahora", return_value=NOW), \
                patch.object(meteo, "consultar_captura_zc", side_effect=RuntimeError("Captura ausente")) as leer, \
                patch.object(app.requests, "get", side_effect=RuntimeError("API indisponible")) as directo, \
                patch.object(recovery, "_leer_red", return_value=shared()):
            result = app.obtener_datos_ecmwf()
        leer.assert_called_once()
        self.assertEqual(directo.call_count, 2)
        self.assertEqual(len(result), 10)
        self.assertTrue(all(x["_origen_meteorologico"] == "red_integrada" for x in result))


if __name__ == "__main__":
    unittest.main()

