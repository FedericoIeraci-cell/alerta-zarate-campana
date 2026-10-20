"""render_app completo conserva lluvia parcial y ausencias al cambiar de nodo."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def ejecutar_portada_completa_zc():
    import plotly.express as px
    import plotly.graph_objects as go
    import streamlit as st
    import streamlit.components.v1 as components
    from test_recuperacion_meteo_portada import NOW, weather

    spec = importlib.util.spec_from_file_location('_zc_app_portada_completa', ROOT / 'app.py')
    app = importlib.util.module_from_spec(spec)
    with patch.dict(os.environ, {'ALA_MONITOR_HEADLESS': '1'}):
        spec.loader.exec_module(app)
    app.st, app.px, app.go, app.components = st, px, go, components
    app.ahora = lambda: NOW
    raw = [dict(weather(n), _consulta_meteorologica=NOW.isoformat()) for n in app.NODOS]
    raw[-1] = {'error': 'Fuente ausente en el escenario controlado'}
    filas = [app.procesar_nodo(n, r, referencia_historica=NOW)
             for n, r in zip(app.NODOS, raw)]
    st.session_state['firma_cobertura'] = app.firma_cobertura()
    if 'df_alerta' not in st.session_state:
        st.session_state['df_alerta'] = app.pd.DataFrame(filas)
        st.session_state['raw_ecmwf'] = deepcopy(raw)
        st.session_state['localidad_detalle'] = app.NODOS[0]['localidad']
    st.session_state['zc_alturas_locales_resultado'] = {'observaciones': {}, 'referencias': {}}
    app.obtener_datos_ecmwf = Mock(side_effect=AssertionError('No renovar el fixture vigente'))
    app.vigilar_actualizacion_meteorologica = Mock()
    app.obtener_secrets_telegram = lambda: ('', '')
    app.HISTORY_FILE = SimpleNamespace(exists=lambda: False)
    app.guardar_historial = Mock()
    secundarios = ('mostrar_prevencion_inundaciones_zc', 'mostrar_vigencia_para_respuesta',
                   'mostrar_cuenca_parana_zc', 'mostrar_historicos_cuenca_zc',
                   'mostrar_conexion_portada_zc', 'mostrar_alturas_locales_zc',
                   'mostrar_paneles_ficha', 'mostrar_radar_smn', 'mostrar_datos_smn',
                   'mostrar_recomendaciones_alerta', 'estado_telegram_ui', 'mostrar_windy',
                   'mostrar_goes19')
    for nombre in secundarios:
        setattr(app, nombre, Mock())
    app.consultar_cuenca_parana_zc = lambda: {}
    app.construir_decision_cuenca_zc = lambda *args: {}
    app.cargar_red_integrada_zc = lambda: SimpleNamespace(
        consultar_red_integrada=lambda: {}, altura_automatica_zarate_de_red=lambda *args, **kwargs: None,
        mostrar_red_integrada=Mock())
    envios = {nombre: Mock(side_effect=AssertionError('Telegram prohibido'))
              for nombre in ('enviar_telegram', 'enviar_telegram_detallado', 'procesar_alertas_telegram')}
    for nombre, control in envios.items():
        setattr(app, nombre, control)
    app.render_app()
    st.session_state['prueba_render_completo'] = True
    st.session_state['prueba_envios'] = sum(e.call_count for e in envios.values())
    st.session_state['prueba_primera'] = app.NODOS[0]['localidad']
    st.session_state['prueba_ultima'] = app.NODOS[-1]['localidad']


class PortadaCompletaZCTests(unittest.TestCase):
    def revisar(self, at):
        self.assertFalse(at.exception)
        self.assertTrue(at.session_state['prueba_render_completo'])
        self.assertEqual(at.session_state['prueba_envios'], 0)
        filas = at.session_state['df_operativo']
        self.assertEqual(len(filas), 10)
        self.assertEqual(int(filas['cobertura_lluvia_futura_24'].sum()), 9)
        self.assertEqual(int(filas['cobertura_lluvia_futura_72'].sum()), 9)
        self.assertTrue(filas['indice'].isna().all())
        self.assertEqual(filas.iloc[0]['lluvia_futura_72'], 0.0)
        self.assertTrue(at.session_state['df_operativo'].iloc[-1]['nivel'] == 'SIN DATOS')
        elementos = list(at.main)
        mapas = [(i, e) for i, e in enumerate(elementos)
                 if e.type == 'iframe' and 'id="mapa-litoral-datos"' in e.proto.srcdoc]
        self.assertEqual(len(mapas), 1, 'El placeholder reemplaza la vista inicial')
        posicion, mapa = mapas[0]
        for i, e in enumerate(elementos):
            if e.type == 'tab_container' or (e.type == 'markdown' and 'class="hero"' in e.value):
                self.assertLess(posicion, i)
        selector = next(i for i, e in enumerate(elementos)
                        if e.type == 'selectbox' and e.key == 'localidad_detalle')
        fichas = [(i, e.value) for i, e in enumerate(elementos)
                  if e.type == 'markdown' and '<section class="zc-portada"' in e.value]
        self.assertEqual(len(fichas), 1)
        self.assertLess(posicion, selector)
        self.assertLess(selector, fichas[0][0])
        bloque = re.search(r'<script id="mapa-litoral-datos" type="application/json">(.*?)</script>',
                           mapa.proto.srcdoc, re.S)
        datos = json.loads(bloque.group(1))
        self.assertEqual(len(datos['puntos']), 10)
        self.assertTrue(all(p['nivel'] == 'SIN DATOS' for p in datos['puntos']))
        primero = next(p for p in datos['puntos'] if p['nombre'] == at.session_state['prueba_primera'])
        ultimo = next(p for p in datos['puntos'] if p['nombre'] == at.session_state['prueba_ultima'])
        self.assertIn('Lluvia prevista · 72 h: 0.0 mm', primero['popup'])
        self.assertNotIn('0.0 mm', ultimo['popup'])
        return fichas[0][1]

    def test_render_completo_con_lluvia_cero_sin_suelo_y_una_fuente_ausente(self):
        codigo = (f'import sys\nsys.path.insert(0,{str(ROOT)!r})\n'
                  f'sys.path.insert(0,{str(ROOT / "tests")!r})\n'
                  'from test_portada_completa_zc import ejecutar_portada_completa_zc\n'
                  'ejecutar_portada_completa_zc()\n')
        with patch('requests.sessions.Session.request', side_effect=AssertionError('Red prohibida')) as http, \
                patch('urllib.request.urlopen', side_effect=AssertionError('Red prohibida')) as urlopen:
            at = AppTest.from_string(codigo, default_timeout=20).run()
            primera = self.revisar(at)
            self.assertIn('0.0 mm', primera)
            at.selectbox(key='localidad_detalle').set_value(at.session_state['prueba_ultima']).run()
            ausente = self.revisar(at)
            self.assertNotIn('0.0 mm', ausente)
            http.assert_not_called()
            urlopen.assert_not_called()


if __name__ == '__main__':
    unittest.main()

