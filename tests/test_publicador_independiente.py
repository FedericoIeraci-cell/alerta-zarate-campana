"""Aislamiento real, conservación de fechas y publicación atómica sin avisos."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest.mock import Mock, patch

import meteorologia_compartida as met
import publicar_datos_zc as pub
import red_integrada as red

NOW = datetime.now(timezone.utc).replace(microsecond=0)


def captura():
    inicio = (NOW - timedelta(days=8)).replace(hour=0, minute=0, second=0, tzinfo=None)
    tiempos = [(inicio + timedelta(hours=i)).isoformat() for i in range(552)]
    raw = [{"latitude": n["lat"], "longitude": n["lon"],
            "timezone": "America/Argentina/Buenos_Aires", "utc_offset_seconds": -10800,
            "hourly": {"time": tiempos, "precipitation": [0.0] * 552, "runoff": [0.0] * 552},
            "hourly_units": {"time": "iso8601", "precipitation": "mm", "runoff": "mm"}}
           for n in red.NODOS_ZC]
    return met.crear_captura(red.NODOS_ZC, raw, NOW)


class FakeAPI:
    def __init__(self, fallo=None):
        self.head = None
        self.entries = []
        self.calls = []
        self.fallo = fallo

    def request(self, method, url, **kwargs):
        prefix = "https://api.github.com/repos/" + pub.REPOSITORY
        assert url.startswith(prefix), "Una publicación ZC nunca contacta el repositorio ALA"
        path = url[len(prefix):]
        data = kwargs.get("json", {})
        self.calls.append((method, path, deepcopy(data)))
        status = 200
        if method == "GET" and path == "": value = {"default_branch": "main"}
        elif method == "GET" and path == "/git/ref/heads/" + pub.STATE_BRANCH:
            status = 404 if self.head is None else 200
            value = {"object": {"sha": self.head}}
        elif method == "GET" and path == "/git/ref/heads/main": value = {"object": {"sha": "a" * 40}}
        elif method == "POST" and path == "/git/refs": self.head = data["sha"]; value = {}
        elif method == "GET" and path.startswith("/git/commits/"): value = {"tree": {"sha": "b" * 40}}
        elif method == "POST" and path == "/git/blobs":
            import base64
            body = base64.b64decode(data["content"])
            sha = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            value = {"sha": "f" * 40 if self.fallo == "blob" else sha}
        elif method == "POST" and path == "/git/trees":
            assert data["base_tree"] == "b" * 40
            self.entries = data["tree"]; value = {"sha": "c" * 40}
        elif method == "POST" and path == "/git/commits": value = {"sha": "d" * 40}
        elif method == "PATCH":
            assert data["force"] is False
            status = 409 if self.fallo == "conflicto" else 200
            if status == 200: self.head = "e" * 40 if self.fallo == "rama" else data["sha"]
            value = {}
        elif method == "GET" and path.startswith("/git/trees/"): value = {"tree": self.entries, "truncated": False}
        else: raise AssertionError((method, path))
        return Mock(status_code=status, json=lambda: value)


class PublicadorIndependienteTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch("requests.sessions.Session.request", side_effect=AssertionError("No HTTP real ni avisos"))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.meteo = patch.object(met, "crear_captura_zc", return_value=captura()).start()
        self.hidro = patch.object(red, "consultar_zc_red", return_value={"nodos": [], "rios": [], "fuentes": [
            {"organismo": "Open-Meteo / ECMWF", "error": "0/10 provisional"}]}).start()
        self.addCleanup(patch.stopall)

    def test_proceso_local_completo_no_lee_ala_ni_repite_consulta_meteo(self):
        store = Mock()
        with patch.object(red, "consultar_red_integrada", side_effect=AssertionError("No respaldo si fue exitosa")), \
             patch.object(red, "consultar_meteorologia_zc", side_effect=AssertionError("No repetir meteorología")):
            estado, documento = pub.ejecutar(dry_run=False, publicador=store)
        archivos = store.publicar.call_args.args[0]
        self.assertEqual(set(archivos), pub.ALLOWED_FILES)
        self.assertEqual(len(documento["nodos"]), 10)
        self.assertEqual(documento["regiones"], ["Zárate–Campana"])
        self.assertFalse(estado["envia_telegram"])
        self.assertEqual(estado["coverage"]["meteorologia"]["vigentes"], 10)
        self.assertEqual(self.hidro.call_args.kwargs["meteorologia"], [])
        self.assertEqual(estado["errors"], [])
        meteo = [f for f in documento["fuentes"] if f["organismo"] == "Open-Meteo / ECMWF"]
        self.assertEqual(len(meteo), 1)
        self.assertEqual(meteo[0]["error"], "")

    def test_fallo_completo_no_sobrescribe_respaldo_ni_fabrica_fecha(self):
        self.meteo.side_effect = met.CapturaMeteorologicaError("Consulta ZC, timeout_lectura.")
        anterior = NOW - timedelta(hours=2)
        nodos = [red._guardar_grilla_zc(red.parsear_meteorologia_zc(n, d, anterior, NOW), d)
                 for n, d in zip(red.NODOS_ZC, captura()["datos"])]
        store = Mock()
        with patch.object(red, "consultar_red_integrada", return_value={}), \
             patch.object(red, "consultar_meteorologia_zc", return_value=nodos):
            estado, doc = pub.ejecutar(dry_run=False, publicador=store)
        self.assertNotIn(met.SNAPSHOT_ZC_PATH, store.publicar.call_args.args[0])
        self.assertEqual(estado["health"], "error_meteorologia")
        self.assertTrue(all(red._fecha(n["fecha_calculo"]) == anterior for n in doc["nodos"]))
        self.assertFalse(estado["meteorologia_completa_publicada"])

    def test_dry_run_no_construye_publicador_ni_escribe(self):
        with patch.object(pub, "GitHubPublicador", side_effect=AssertionError("Sin credenciales")):
            estado, doc = pub.ejecutar()
        self.assertTrue(estado["dry_run"])
        self.assertFalse(estado["red_integrada_publicada"])

    def test_solo_escribe_su_repo_su_rama_y_los_tres_archivos_juntos(self):
        api = FakeAPI()
        store = pub.GitHubPublicador("credencial_prueba", session=api)
        estado, _ = pub.ejecutar(dry_run=False, publicador=store)
        self.assertEqual(estado["confirmacion"]["commit_sha"], "d" * 40)
        self.assertEqual({e["path"] for e in api.entries}, pub.ALLOWED_FILES)
        self.assertFalse(any("sqlite" in path or "telegram" in path for _, path, _ in api.calls))
        with self.assertRaises(pub.PublicacionError):
            pub.GitHubPublicador("credencial_prueba", "FedericoIeraci-cell/Alerta-Litoral")

    def test_no_declara_exito_si_hay_conflicto_blob_distinto_o_rama_sustituida(self):
        for fallo in ("conflicto", "blob", "rama"):
            api = FakeAPI(fallo)
            store = pub.GitHubPublicador("credencial_prueba", session=api)
            with self.subTest(fallo=fallo), self.assertRaises(pub.PublicacionError):
                pub.ejecutar(dry_run=False, publicador=store)

    def test_lectores_y_workflow_solo_usan_estado_propio(self):
        from pathlib import Path
        self.assertEqual(red.REPOSITORY, pub.REPOSITORY)
        self.assertEqual(red.STATE_BRANCH, pub.STATE_BRANCH)
        self.assertEqual(red.MONITOR_STATUS_PATH, pub.STATUS_PATH)
        self.assertIn(pub.REPOSITORY + "/" + pub.STATE_BRANCH, met.SNAPSHOT_ZC_URL)
        workflow = Path(__file__).resolve().parents[1] / ".github/workflows/zc-datos.yml"
        texto = workflow.read_text()
        self.assertNotIn("TELEGRAM", texto)
        self.assertNotIn("secrets.", texto)
        self.assertNotIn("monitor.py", texto)
        self.assertIn("publicar_datos_zc.py --publicar", texto)


if __name__ == "__main__":
    unittest.main()
