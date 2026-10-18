"""Interacciones reales de Streamlit; no realizan consultas externas."""
import ast
import json
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from test_portada_zc import CifrasHTML

ROOT = Path(__file__).resolve().parents[1]
PATHS = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nsys.path.insert(0, {str(ROOT/'tests')!r})\n"


class PortadaStreamlitTests(unittest.TestCase):
    def cifra_visible(self, at, clave):
        resumenes=[m.value for m in at.markdown if '<section class="zc-portada"' in m.value]
        self.assertEqual(len(resumenes),1)
        return CifrasHTML(resumenes[0]).cifras[clave]['texto']

    def test_mapa_iframe_conserva_diez_referencias_y_su_alcance_meteorologico(self):
        # Ejecutar la llamada de render_app evita mantener una copia de su
        # integración. El resto de la aplicación consulta fuentes externas.
        arbol=ast.parse((ROOT/'app.py').read_text(encoding='utf-8'))
        render=next(n for n in arbol.body if isinstance(n,ast.FunctionDef) and n.name=='render_app')
        llamadas=[n for n in ast.walk(render) if isinstance(n,ast.Expr)
                  and isinstance(n.value,ast.Call)
                  and any(isinstance(c,ast.Call) and isinstance(c.func,ast.Name)
                          and c.func.id=='html_mapa_litoral' for c in ast.walk(n))]
        self.assertEqual(len(llamadas),1,'La portada debe integrar un solo mapa local')
        codigo=PATHS+'''
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from test_evidencia_app_zc import cargar_app, REF
from test_portada_zc import localidad
from mapa_litoral import html_mapa_litoral
from portada_zc import hover_meteorologico_zc
app=cargar_app()
app.ahora=lambda: REF
referencia_mapa=REF
filas=[]
for i,nodo in enumerate(app.NODOS):
    fila={**localidad(),**nodo,'indice':[10.,45.,70.,None][i%4],
          'actualizado':REF.strftime('%d/%m/%Y %H:%M'),
          'estado_datos':'OK' if i%4!=3 else 'PARCIAL',
          'cobertura_meteorologica':i%4!=3,
          'nivel_integrado':'ROJO','fuente_meteorologica':'https://api.open-meteo.com/v1/forecast'}
    if i%4==3:
        fila.update({campo:None for campo in ('lluvia_futura_24','lluvia_futura_72',
                    'lluvia_futura_7d','humedad_suelo_promedio','runoff_futuro_72')})
    filas.append(fila)
df_alerta=app.integrar_semaforo(pd.DataFrame(filas))
original=df_alerta.copy(deep=True)
st.session_state['zc_cuenca_decision']={'prioridad':2,'motivos':['Referencia de río alcanzada en Campana.']}
'''+ast.unparse(llamadas[0])+'''
pd.testing.assert_frame_equal(df_alerta,original)
assert st.session_state['zc_cuenca_decision']=={'prioridad':2,'motivos':['Referencia de río alcanzada en Campana.']}
st.session_state['mapa_esperado']={r['localidad']:r['nivel'] for r in df_alerta.to_dict('records')}
'''
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Red bloqueada')), \
                patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Red bloqueada')):
            at=AppTest.from_string(codigo).run()
        self.assertFalse(at.exception)
        mapas=[x for x in at.get('iframe') if 'id="mapa-litoral"' in x.proto.srcdoc]
        self.assertEqual(len(mapas),1)
        bloque=re.search(r'<script id="mapa-litoral-datos" type="application/json">(.*?)</script>',
                         mapas[0].proto.srcdoc,re.S)
        self.assertIsNotNone(bloque)
        datos=json.loads(bloque.group(1))
        self.assertEqual(datos['leyenda'],'Índice meteorológico experimental')
        self.assertEqual(datos['ajustar_a'],'puntos')
        self.assertEqual(datos['geometrias']['features'],[])
        self.assertEqual(datos['omitidos'],0)
        self.assertEqual(len(datos['puntos']),10)
        self.assertEqual({p['nombre']:p['nivel'] for p in datos['puntos']},
                         at.session_state['mapa_esperado'])
        self.assertEqual({p['nivel'] for p in datos['puntos']},
                         {'VERDE','AMARILLO','ROJO','SIN DATOS'})
        for punto in datos['puntos']:
            self.assertIn('Semáforo meteorológico: '+punto['nivel'],punto['popup'])
            self.assertIn('Cálculo: 17/10/2026 18:00',punto['popup'])
            self.assertIn('Río y preparación regional: consultar la ficha superior.',punto['popup'])
            if punto['nivel']=='SIN DATOS':
                self.assertEqual(punto['color'],'#64748b')
                self.assertIn('Sin dato',punto['popup'])
                self.assertNotIn('7.1 mm',punto['popup'])
            else:
                self.assertIn('Lluvia prevista · 72 h: 7.1 mm',punto['popup'])
                self.assertIn('0.300 m³/m³',punto['popup'])

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
            self.assertIn('1.55 m',self.cifra_visible(at,'rio'))
            self.assertIn('0.0 mm',self.cifra_visible(at,'lluvia24'))
            at.selectbox[0].set_value('Campana').run()
            self.assertFalse(at.exception)
            self.assertIn('1.20 m',self.cifra_visible(at,'rio'))
            at.radio[0].set_value('Productor / trabajo rural').run()
            self.assertFalse(at.exception)
            self.assertTrue(any('Confirmá acceso y comunicación' in m.value for m in at.markdown))
            at.checkbox[0].check().run()
            self.assertFalse(at.exception)
            self.assertIn('Sin dato actual',self.cifra_visible(at,'rio'))
            self.assertNotIn('1.20 m',self.cifra_visible(at,'rio'))

    def test_automatica_zarate_actual_se_separa_de_puertos_y_no_se_hereda(self):
        codigo=PATHS+'''
import streamlit as st
from datetime import timedelta
from test_portada_zc import localidad, observado, cap
from test_hidrometria_local import parsear, REF, ULTIMA
from portada_zc import construir_portada_zc, mostrar_portada_zc
partido=st.selectbox('Referencia de prueba',['Zárate','Campana'])
vencida=st.checkbox('Avanzar hasta después de seis horas')
invalidar=st.checkbox('Simular fuente automática inválida')
ref=ULTIMA+timedelta(hours=6,seconds=1) if vencida else REF
row={**localidad(),'partido':partido,'localidad':partido+' centro'}
rio={**observado(),'nombre':partido,'serie_id':40 if partido=='Zárate' else 41}
automatica=parsear()
if invalidar:
    automatica['fuente']='https://ejemplo.org/lectura'
resumen=construir_portada_zc(row,{'prioridad':2,'motivos':['Campana: altura observada alcanza referencia INA de alerta.']},
    {'emision':ref},rio,cap(),{},ref,observacion_automatica=automatica)
mostrar_portada_zc(st,resumen)
st.session_state['prioridad_de_prueba']=resumen['prioridad']
'''
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Red bloqueada')), \
                patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Red bloqueada')):
            at=AppTest.from_string(codigo).run()
            self.assertFalse(at.exception)
            self.assertIn('1.12 m',self.cifra_visible(at,'rio'))
            self.assertEqual(at.session_state['prioridad_de_prueba'],2)
            self.assertTrue(any('Puerto de Zárate' in m.value for m in at.markdown))
            self.assertTrue(any('2.00 m' in m.value for m in at.markdown))
            at.selectbox[0].set_value('Campana').run()
            self.assertFalse(at.exception)
            self.assertIn('Sin dato actual',self.cifra_visible(at,'rio'))
            self.assertNotIn('1.12 m',self.cifra_visible(at,'rio'))
            at.selectbox[0].set_value('Zárate').run()
            at.checkbox[0].check().run()
            self.assertFalse(at.exception)
            self.assertIn('Sin dato actual',self.cifra_visible(at,'rio'))
            self.assertEqual(at.session_state['prioridad_de_prueba'],2)
            at.checkbox[0].uncheck().run()
            at.checkbox[1].check().run()
            self.assertFalse(at.exception)
            self.assertIn('Sin dato actual',self.cifra_visible(at,'rio'))
            self.assertFalse(any('ejemplo.org' in str(b.proto.url) for b in at.get('link_button')))

    def test_alturas_en_dos_paneles_usan_la_misma_evidencia_y_no_la_lectura_archivada(self):
        codigo=PATHS+'''
import streamlit as st
import plotly.express as px
import pandas as pd
from datetime import timedelta
from test_evidencia_app_zc import cargar_app
from test_hidrometria_local import parsear, REF
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
automatica=parsear()
def no_reconsultar():
    raise AssertionError('Los paneles deben reutilizar la consulta de Prefectura del snapshot')
app.obtener_alturas_prefectura_zc=no_reconsultar
with st.expander('Alturas de ambos puertos'):
    app.mostrar_alturas_locales_zc(datos,key_prefix='ficha_',observacion_automatica=automatica)
app.mostrar_alturas_locales_zc(datos,key_prefix='modelo_',observacion_automatica=automatica)
'''
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Red bloqueada')):
            at=AppTest.from_string(codigo).run()
        self.assertFalse(at.exception)
        actuales=[x.value for x in at.metric if x.label=='INA · altura observada vigente']
        self.assertEqual(actuales,['1.55 m','1.20 m','1.55 m','1.20 m'])
        automaticas=[x.value for x in at.metric if x.label=='RHN / INA · altura automática vigente']
        self.assertEqual(automaticas,['1.12 m','1.12 m'])
        fechas_automaticas=[c.value for c in at.caption if '17/10/2026 21:00 ART' in c.value]
        self.assertEqual(len(fechas_automaticas),2)
        self.assertEqual(fechas_automaticas[0],fechas_automaticas[1])
        archivo=[x.value for x in at.metric if x.label=='Lectura documental conservada']
        self.assertEqual(archivo,['1.10 m','1.10 m'])


if __name__ == '__main__':
    unittest.main()
