"""Interacciones reales de Streamlit; no realizan consultas externas."""
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
PATHS = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nsys.path.insert(0, {str(ROOT/'tests')!r})\n"


class PortadaStreamlitTests(unittest.TestCase):
    def test_localidad_y_publico_actualizan_la_ficha_sin_perder_ausencias(self):
        codigo=PATHS+'''
import streamlit as st
from test_portada_zc import REF, localidad, observado, cap
from portada_zc import construir_portada_zc, mostrar_portada_zc
partido=st.selectbox('Localidad de prueba',['Zárate','Campana'])
faltante=st.checkbox('Simular fuente de río ausente')
row={**localidad(),'partido':partido,'localidad':partido+' centro'}
rio={**observado(),'serie_id':40 if partido=='Zárate' else 41,
     'altura_m':1.55 if partido=='Zárate' else 1.2}
if faltante:
    rio={}
resumen=construir_portada_zc(row,{'prioridad':1,'nivel_preparacion':'VIGILANCIA REFORZADA',
    'motivos':['Aguas altas en la cuenca.']},{'emision':REF},rio,cap(),{},REF)
mostrar_portada_zc(st,resumen)
'''
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Red bloqueada')):
            at=AppTest.from_string(codigo).run()
            self.assertFalse(at.exception)
            self.assertEqual(next(x.value for x in at.metric if x.label=='Altura observada vigente'),'1.55 m')
            at.selectbox[0].set_value('Campana').run()
            self.assertFalse(at.exception)
            self.assertEqual(next(x.value for x in at.metric if x.label=='Altura observada vigente'),'1.20 m')
            at.radio[0].set_value('Productor / trabajo rural').run()
            self.assertFalse(at.exception)
            at.checkbox[0].check().run()
            self.assertFalse(at.exception)
            self.assertEqual(next(x.value for x in at.metric if x.label=='Altura observada vigente'),'Sin dato actual')

    def test_alturas_en_dos_paneles_usan_la_misma_evidencia_y_no_la_lectura_archivada(self):
        codigo=PATHS+'''
import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import timedelta
from test_evidencia_app_zc import cargar_app, REF
app=cargar_app()
app.st=st
app.px=px
app.ahora=lambda: REF
observaciones={}
for nombre, config in app._zc_hidro_estaciones.items():
    observaciones[nombre]={'df':pd.DataFrame([{'fecha':REF-timedelta(hours=1),
        'observado':1.55 if nombre=='Zárate' else 1.2,'zona_horaria_verificada':True}]),
        'serie_id':config['observada'],'url':'https://alerta.ina.gob.ar/','consulta':REF.isoformat(),'error':''}
pna={'fuente':'https://contenidosweb.prefecturanaval.gob.ar/alturas',
     'error':'No se recuperó una consulta actual de Prefectura','registros':{},
     'referencia_documental':{'consulta_original':'14/10/2026',
       'registros':{'Zárate':{'altura_m':1.1,'fecha_publicada':'14/OCT/26 - 0000',
         'tendencia_publicada':'Sin cambios','alerta_m':2.,'evacuacion_m':2.2}}}}
datos=app.snapshot_alturas_locales_zc(observaciones,{'referencias':{}},pna,REF)
def no_reconsultar():
    raise AssertionError('Los paneles deben reutilizar la consulta de Prefectura del snapshot')
app.obtener_alturas_prefectura_zc=no_reconsultar
with st.expander('Alturas de ambos puertos'):
    app.mostrar_alturas_locales_zc(datos,key_prefix='ficha_')
app.mostrar_alturas_locales_zc(datos,key_prefix='modelo_')
'''
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Red bloqueada')):
            at=AppTest.from_string(codigo).run()
        self.assertFalse(at.exception)
        actuales=[x.value for x in at.metric if x.label=='INA · altura observada vigente']
        self.assertEqual(actuales,['1.55 m','1.20 m','1.55 m','1.20 m'])
        archivo=[x.value for x in at.metric if x.label=='Lectura documental conservada']
        self.assertEqual(archivo,['1.10 m','1.10 m'])


if __name__ == '__main__':
    unittest.main()
