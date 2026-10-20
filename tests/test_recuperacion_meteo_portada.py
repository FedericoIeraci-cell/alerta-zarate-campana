"""Grillas compartidas como respaldo: identidad, fechas y datos parciales."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import red_integrada as red
import recuperacion_meteo_zc as recovery

ART = ZoneInfo("America/Argentina/Buenos_Aires")
NOW = datetime(2026, 10, 20, 14, 0, tzinfo=ART)


def weather(nodo, *, cero=True):
    first = NOW - timedelta(days=8)
    hours = [(first + timedelta(hours=i)).replace(tzinfo=None).isoformat() for i in range(577)]
    return {
        "latitude": nodo["lat"], "longitude": nodo["lon"],
        "timezone": "America/Argentina/Buenos_Aires", "utc_offset_seconds": -10800,
        "hourly_units": {"time": "iso8601", "precipitation": "mm", "runoff": "undefined"},
        "hourly": {"time": hours, "precipitation": [0.0 if cero else 1.0] * len(hours),
                   "runoff": [None] * len(hours)},
    }


def shared(*, consulted=None, generated=None):
    consulta = consulted or NOW - timedelta(minutes=20)
    nodes = []
    for nodo in red.NODOS_ZC:
        raw = weather(nodo)
        parsed = red.parsear_meteorologia_zc(nodo, raw, consulta, NOW)
        nodes.append(red._guardar_grilla_zc(parsed, raw))
    return red.construir_red_integrada([], {}, zc={"nodos": nodes, "rios": [], "fuentes": []},
                                      referencia=generated or NOW, monitor={})


class SharedRecovery(unittest.TestCase):
    def setUp(self):
        self.nodos = deepcopy(red.NODOS_ZC)
        self.failure = [{"error": "ReadTimeout"} for _ in self.nodos]
        captura = patch.object(recovery, "_leer_captura_completa", return_value=None)
        captura.start()
        self.addCleanup(captura.stop)

    def recover(self, datos=None, primary=None):
        return recovery.recuperar_respuestas_zc(self.nodos, self.failure if primary is None else primary,
                                              NOW, shared() if datos is None else datos)

    def test_rescata_diez_grillas_con_ceros_reales_y_sin_inventar_otras_variables(self):
        result = self.recover()
        self.assertEqual(len(result), 10)
        self.assertTrue(all("error" not in row for row in result))
        self.assertTrue(all(row["hourly"]["precipitation"][0] == 0.0 for row in result))
        self.assertTrue(all(row["hourly"]["runoff"][0] is None for row in result))
        self.assertTrue(all("temperature_2m" not in row["hourly"] for row in result))
        self.assertTrue(all("indice" not in row for row in result))

    def test_fecha_original_no_se_renueva_por_abrir_la_pagina(self):
        result = self.recover()
        self.assertTrue(all(datetime.fromisoformat(row["_consulta_meteorologica"]) == NOW - timedelta(minutes=20) for row in result))
        self.assertTrue(all(datetime.fromisoformat(row["_fecha_ultimo_intento_meteorologico"]) == NOW for row in result))

    def test_prioriza_respuesta_directa_sin_consultar_la_red(self):
        primary = [dict(weather(nodo, cero=False), _consulta_meteorologica=NOW.isoformat()) for nodo in self.nodos]
        with patch.object(recovery, "_leer_red", side_effect=AssertionError("No hace falta respaldo")):
            self.assertEqual(self.recover(primary=primary), primary)

    def test_fallo_en_un_punto_no_reemplaza_los_otros(self):
        primary = [dict(weather(nodo, cero=False), _consulta_meteorologica=NOW.isoformat()) for nodo in self.nodos]
        primary[2] = {"error": "ReadTimeout"}
        result = self.recover(primary=primary)
        self.assertEqual(result[0], primary[0])
        self.assertEqual(result[2]["hourly"]["precipitation"][0], 0.0)

    def test_captura_vencida_no_se_usa_como_actual(self):
        data = shared()
        data["generated_at"] = (NOW - timedelta(hours=4)).isoformat()
        self.assertEqual(self.recover(data), self.failure)

    def test_grilla_antigua_no_se_renueva_con_snapshot_reciente(self):
        data = shared()
        for row in data["nodos"]:
            if row["red"] == "Zárate–Campana":
                row["fecha_consulta"] = (NOW - timedelta(hours=4)).isoformat()
        self.assertEqual(self.recover(data), self.failure)

    def test_fecha_futura_sin_zona_o_sin_hora_no_se_usa(self):
        for consulta in ((NOW + timedelta(hours=1)).isoformat(), "2026-10-20T13:40:00", "2026-10-20"):
            with self.subTest(consulta=consulta):
                data = shared()
                for row in data["nodos"]:
                    if row["red"] == "Zárate–Campana": row["fecha_consulta"] = consulta
                self.assertEqual(self.recover(data), self.failure)

    def test_rechaza_cambio_de_fuente(self):
        data = shared()
        for row in data["nodos"]:
            if row["red"] == "Zárate–Campana": row["fuente"] = "https://example.org/forecast"
        self.assertEqual(self.recover(data), self.failure)

    def test_rechaza_identidad_geografica_del_catalogo_incorrecta(self):
        data = shared()
        data["nodos"][-1]["lat"] += 0.1
        self.assertEqual(self.recover(data), self.failure)

    def test_rechaza_celda_lejana_en_grilla_sin_afectar_otras_nueve(self):
        data = shared()
        data["nodos"][-1]["grilla_verificada"]["latitude"] = 30
        result = self.recover(data)
        self.assertEqual(result[-1], self.failure[-1])
        self.assertEqual(sum("error" not in row for row in result), 9)

    def test_rechaza_unidad_lluvia_o_grilla_duplicada(self):
        for mutation in ("unit", "time"):
            with self.subTest(mutation=mutation):
                data = shared()
                for row in data["nodos"]:
                    if row["red"] != "Zárate–Campana": continue
                    grid = row["grilla_verificada"]
                    if mutation == "unit": grid["hourly_units"]["precipitation"] = "inch"
                    else: grid["hourly"]["time"][1] = grid["hourly"]["time"][0]
                self.assertEqual(self.recover(data), self.failure)

    def test_no_fabrica_grilla_desde_un_resumen_acumulado(self):
        data = shared()
        for row in data["nodos"]:
            row.pop("grilla_verificada", None)
        self.assertEqual(self.recover(data), self.failure)

    def test_fuente_comun_caida_no_hace_fallar_el_panel(self):
        self.assertEqual(self.recover({"error": "Sin informe"}), self.failure)

    def test_no_muta_la_grilla_ni_respuestas_que_recibe(self):
        data = shared(); before = deepcopy(data)
        primary = deepcopy(self.failure); snapshot = deepcopy(primary)
        self.recover(data, primary)
        self.assertEqual(data, before)
        self.assertEqual(primary, snapshot)


if __name__ == "__main__":
    unittest.main()
