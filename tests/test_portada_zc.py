"""La ficha pública conserva ausencias, fechas, escalas y alcance regional."""
from copy import deepcopy
from datetime import datetime, timedelta
from html.parser import HTMLParser
import unittest

from portada_zc import (TZ, construir_portada_zc, hover_meteorologico_zc, html_resumen_portada_zc,
                        resumir_lluvia, resumir_represa, resumir_rio, resumir_smn)

REF = datetime(2026, 10, 17, 18, 0, tzinfo=TZ)


class CifrasHTML(HTMLParser):
    """Lee las cifras visibles, sin confundirlas con datos de los desplegables."""
    def __init__(self, markup):
        super().__init__()
        self.cifras, self.actual = {}, None
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        atributos = dict(attrs)
        if tag == 'article' and atributos.get('data-cifra'):
            self.actual = atributos['data-cifra']
            self.cifras[self.actual] = {'texto': [], 'fuentes': []}
        if self.actual and tag == 'a':
            self.cifras[self.actual]['fuentes'].append(atributos.get('href'))

    def handle_data(self, data):
        if self.actual and data.strip():
            self.cifras[self.actual]['texto'].append(data.strip())

    def handle_endtag(self, tag):
        if tag == 'article':
            self.actual = None


def localidad():
    return {'localidad':'Zárate centro','partido':'Zárate','actualizado':'17/10/2026 17:50',
            'consulta_meteorologica':(REF-timedelta(minutes=10)).isoformat(),
            'estado_datos':'OK','cobertura_meteorologica':True,'indice':12.4,'nivel':'VERDE',
            'lluvia_futura_24':0.,'lluvia_futura_72':7.1,'lluvia_futura_7d':23.5,
            'humedad_suelo_promedio':.30,'runoff_futuro_72':1.2}


def observado():
    return {'nombre':'Zárate','serie_id':40,'fecha':REF-timedelta(hours=1),
            'altura_m':1.55,'observacion_vigente':True,'umbral_publicado':True,
            'alerta_m':2.,'evacuacion_m':2.2,'fuente':'https://alerta.ina.gob.ar/a5/series/40',
            'zona_horaria_verificada':True,'error':''}


def cap():
    return {'fecha_feed':REF-timedelta(minutes=12),'consultado':REF-timedelta(minutes=10),
            'filas':[],'error':'','fallos':0,'truncado':False,
            'fechas_no_confirmadas_locales':0,'replacements_no_confirmados':0}


def aviso():
    return {'id':'aviso-1','emision':REF-timedelta(hours=1),'desde':REF-timedelta(minutes=30),
            'hasta':REF+timedelta(hours=2),'status':'Actual','tipo_mensaje':'Alert',
            'nodos':['Zárate centro'],'areas':['Zárate'],'poligonos':[],
            'url':'https://ssl.smn.gob.ar/CAP/aviso.xml','fenomeno':'Tormentas',
            'severidad_cap':'Severe','referencias':[]}


class PortadaSemanticaTests(unittest.TestCase):
    def test_lectura_automatica_verificada_no_hereda_umbrales_ni_rebaja_prioridad(self):
        from test_hidrometria_local import parsear, REF as ref_automatica
        automatica=parsear()
        original=deepcopy(automatica)
        decision={'prioridad':2,'motivos':['Campana: altura observada alcanza referencia INA de alerta.']}
        resumen=construir_portada_zc(localidad(),decision,{'emision':ref_automatica},observado(),cap(),{},
                    ref_automatica,observacion_automatica=automatica)
        self.assertEqual(automatica,original)
        self.assertEqual(resumen['prioridad'],2)
        self.assertTrue(resumen['observacion_automatica']['vigente'])
        self.assertEqual(resumen['rio']['serie'],40)
        self.assertIsNone(resumen['rio']['altura'])
        self.assertEqual(resumen['rio']['alerta'],2.)
        self.assertFalse(resumen['rio']['comparacion_pronostico_umbral'])
        salida=html_resumen_portada_zc(resumen)
        cifra=CifrasHTML(salida).cifras['rio']
        self.assertIn('1.12 m',cifra['texto'])
        self.assertIn('Río observado · Paraná Las Palmas - Zárate',cifra['texto'])
        self.assertIn('Lectura: 17/10 21:00 ART',cifra['texto'])
        self.assertIn(automatica['fuente'],cifra['fuentes'])
        self.assertNotIn('Por debajo de la referencia de alerta',salida)
        self.assertIn('Campana',resumen['causas'][0])

    def test_automatica_no_se_traslada_a_campana_ni_sobrevive_su_vigencia(self):
        from test_hidrometria_local import parsear, REF as ref_automatica, ULTIMA
        automatica=parsear()
        row={**localidad(),'localidad':'Campana centro','partido':'Campana'}
        puerto={**observado(),'nombre':'Campana','serie_id':41,
                'fuente':'https://alerta.ina.gob.ar/a5/series/41'}
        campana=construir_portada_zc(row,{'prioridad':1},{'emision':ref_automatica},puerto,cap(),{},
                    ref_automatica,observacion_automatica=automatica)
        self.assertIsNone(campana['observacion_automatica'])
        self.assertIn('Sin dato actual',CifrasHTML(html_resumen_portada_zc(campana)).cifras['rio']['texto'])
        tarde=construir_portada_zc(localidad(),{'prioridad':1},{'emision':ref_automatica},observado(),cap(),{},
                    ULTIMA+timedelta(hours=6,seconds=1),observacion_automatica=automatica)
        self.assertFalse(tarde['observacion_automatica']['vigente'])
        self.assertEqual(tarde['observacion_automatica']['altura_m'],1.12)
        cifra=CifrasHTML(html_resumen_portada_zc(tarde)).cifras['rio']['texto']
        self.assertIn('Sin dato actual',cifra)
        self.assertNotIn('1.12 m',cifra)
        self.assertEqual(tarde['prioridad'],1)
        for cambio in ({'serie':40},{'cero_ign_m':0.0},{'fuente':'https://ejemplo.org/observacion'}):
            with self.subTest(cambio=cambio):
                invalida=construir_portada_zc(localidad(),{'prioridad':1},{'emision':ref_automatica},observado(),cap(),{},
                        ref_automatica,observacion_automatica={**automatica,**cambio})
                self.assertFalse(invalida['observacion_automatica']['vigente'])
                self.assertNotIn('1.12 m',CifrasHTML(html_resumen_portada_zc(invalida)).cifras['rio']['texto'])

    def test_cifras_visibles_conservan_cero_fecha_y_fuente_sin_abrir_detalles(self):
        row={**localidad(),'referencia_datos':(REF-timedelta(hours=2)).isoformat()}
        resumen=construir_portada_zc(row,{'prioridad':1},{'emision':REF},observado(),cap(),{},REF)
        cifras=CifrasHTML(html_resumen_portada_zc(resumen)).cifras
        self.assertEqual(set(cifras),{'lluvia24','lluvia72','rio'})
        self.assertIn('0.0 mm',cifras['lluvia24']['texto'])
        self.assertIn('Desde 17/10 16:00 ART',cifras['lluvia24']['texto'])
        self.assertIn(resumen['lluvia']['fuente'],cifras['lluvia24']['fuentes'])
        self.assertIn('1.55 m',cifras['rio']['texto'])
        self.assertIn('Lectura: 17/10 17:00 ART',cifras['rio']['texto'])
        self.assertIn(observado()['fuente'],cifras['rio']['fuentes'])
        vencido=construir_portada_zc(row,{'prioridad':1},{'emision':REF},observado(),cap(),{},REF+timedelta(hours=13))
        viejas=CifrasHTML(html_resumen_portada_zc(vencido)).cifras
        for clave in cifras:
            self.assertIn('Sin dato actual',viejas[clave]['texto'])
        self.assertIn('Último registro disponible: 17/10 17:00 ART',viejas['rio']['texto'])
        self.assertNotIn('1.55 m',viejas['rio']['texto'])

    def test_causas_agrupan_solo_hechos_y_periodos_identicos(self):
        senal={'prioridad':1,'mecanismo':'Tendencia del pronóstico fluvial',
               'horizonte':'Corto · 0–72 h','id_horizonte':'corto','inicio':REF+timedelta(hours=1),
               'fin':REF+timedelta(hours=60),'motivos':['Ascenso previsto de 0.20 m en la propia serie. No demuestra desborde.'],
               'nivel':'VIGILANCIA FLUVIAL · ASCENSO EN EL TRAMO PREVISTO'}
        alertas=[{**senal,'localidad':lugar+' · estación de referencia'} for lugar in ('Zárate','Campana')]
        motivos=['Modelo local · '+a['localidad']+' · '+a['horizonte']+': '+a['motivos'][0] for a in alertas]
        decision={'prioridad':1,'motivos':motivos}
        modelo={'emision':REF,'alertas':alertas}
        anterior=deepcopy(modelo)
        resumen=construir_portada_zc(localidad(),decision,modelo,observado(),cap(),{},REF)
        self.assertEqual(modelo,anterior)
        self.assertEqual(resumen['prioridad'],1)
        self.assertEqual(len(resumen['causas']),1)
        self.assertTrue(all(lugar in resumen['causas'][0] for lugar in ('Zárate','Campana')))
        self.assertIn('0.20 m',resumen['causas'][0])
        self.assertIn('No demuestra desborde',resumen['causas'][0])
        for cambio in ({'fin':REF+timedelta(hours=61)}, {'motivos':['Ascenso previsto de 0.40 m. No demuestra desborde.']}):
            with self.subTest(cambio=cambio):
                distintas=[alertas[0],{**alertas[1],**cambio}]
                nuevos=['Modelo local · '+a['localidad']+' · '+a['horizonte']+': '+a['motivos'][0] for a in distintas]
                resultado=construir_portada_zc(localidad(),{**decision,'motivos':nuevos},{**modelo,'alertas':distintas},observado(),cap(),{},REF)
                self.assertEqual(len(resultado['causas']),2)

    def test_cruce_actual_duplicado_conserva_localidad_sin_doble_causa(self):
        cruce='Campana: altura observada alcanza referencia INA de evacuación; no es una orden de evacuación.'
        modelo={'emision':REF,'alertas':[{'localidad':'Zárate–Campana','prioridad':2,
            'mecanismo':'Evidencia actual de río / parte local','motivos':[cruce],'horizonte':'Corto · 0–72 h'}]}
        decision={'prioridad':2,'motivos':['Prevención local: SMN: aviso local de tormentas.',
                  'Prevención local: '+cruce,'Modelo local · Zárate–Campana · Corto · 0–72 h: '+cruce]}
        resumen=construir_portada_zc(localidad(),decision,modelo,observado(),cap(),{},REF)
        self.assertEqual(resumen['prioridad'],2)
        self.assertEqual(sum(cruce in c for c in resumen['causas']),1)
        self.assertIn('Campana',resumen['causas'][0])
        self.assertTrue(any('SMN:' in c for c in resumen['causas']))
        salida=html_resumen_portada_zc(resumen)
        self.assertEqual(salida.count(cruce),1)
        self.assertNotIn('<details',salida)
        sin_repeticion_preventiva=construir_portada_zc(localidad(),{'prioridad':2},modelo,observado(),cap(),{},REF)
        self.assertIn(cruce,sin_repeticion_preventiva['causas'][0])

    def test_resumen_escapa_nombres_y_causas_externas(self):
        resumen=construir_portada_zc({**localidad(),'localidad':'<img src=x onerror=alert(1)>'},
                 {'prioridad':1,'motivos':['<script>alert(1)</script>']},referencia=REF)
        salida=html_resumen_portada_zc(resumen)
        self.assertNotIn('<script>',salida)
        self.assertNotIn('<img ',salida)
        self.assertIn('&lt;script&gt;',salida)

    def test_lluvia_cero_real_y_ausencia_no_se_confunden(self):
        completa=resumir_lluvia(localidad(),REF)
        self.assertEqual(completa['valores']['lluvia_futura_24'],0.)
        parcial={**localidad(),'estado_datos':'PARCIAL','indice':None,'lluvia_futura_24':None}
        resumen=resumir_lluvia(parcial,REF)
        self.assertIsNone(resumen['valores']['lluvia_futura_24'])
        self.assertEqual(resumen['valores']['lluvia_futura_72'],7.1)
        self.assertEqual(resumen['nivel'],'SIN DATOS')
        self.assertIsNone(resumen['indice'])

    def test_lluvia_vencida_no_se_publica_como_pronostico_actual(self):
        row={**localidad(),'actualizado':'16/10/2026 17:50'}
        resumen=resumir_lluvia(row,REF)
        self.assertFalse(resumen['vigente'])
        self.assertTrue(all(v is None for v in resumen['valores'].values()))
        self.assertNotIn('7.1 mm',hover_meteorologico_zc(row,REF))

    def test_cambio_de_partido_no_traslada_la_escala(self):
        self.assertEqual(resumir_rio('Zárate',observado(),[],REF)['altura'],1.55)
        otra=resumir_rio('Campana',observado(),[],REF)
        self.assertIsNone(otra['altura'])
        self.assertIsNone(otra['alerta'])
        self.assertEqual(otra['serie'],41)

    def test_altura_vencida_futura_sin_zona_o_fuente_no_se_vuelve_actual(self):
        casos=[{'fecha':REF-timedelta(hours=6,seconds=1)},
               {'fecha':REF+timedelta(seconds=1)},
               {'fecha':REF.replace(tzinfo=None)},
               {'observacion_vigente':False},
               {'fuente':'https://ejemplo.org/serie/40'},
               {'altura_m':float('nan')}]
        for cambio in casos:
            with self.subTest(cambio=cambio):
                resumen=resumir_rio('Zárate',{**observado(),**cambio},[],REF)
                self.assertFalse(resumen['vigente'])
                self.assertIsNone(resumen['altura'])

    def test_pronostico_alto_no_se_compara_con_umbral_observado(self):
        prono={'estacion':'Zárate','serie_pronostico':29534,'id':'corto',
               'fuente':'https://alerta.ina.gob.ar/pronostico/29534','vigente':True,
               'emision':REF-timedelta(hours=1),'fin_publicado':REF+timedelta(hours=71),
               'maximo_m_serie_pronostico':7.8}
        resumen=resumir_rio('Zárate',observado(),[prono],REF)
        self.assertTrue(resumen['pronostico_vigente'])
        self.assertEqual(resumen['maximo_previsto'],7.8)
        self.assertFalse(resumen['comparacion_pronostico_umbral'])
        self.assertEqual(resumen['estado'],'Por debajo de la referencia de alerta')
        prono['serie_pronostico']=3405
        self.assertFalse(resumir_rio('Zárate',observado(),[prono],REF)['pronostico_vigente'])

    def test_eby_separa_afluencia_prevista_y_documento_diario(self):
        parte={'url':'https://eby.gov.py/parte','fecha_informe':'2026-10-16',
               'consulta':REF-timedelta(hours=1),'error':None,
               'campos':[{'variable':'caudal_afluente_hoy','tipo':'pronosticado',
                          'unidad':'m³/s','valor':39000,'fecha':'2026-10-16'},
                         {'variable':'caudal_vertido_brazo_principal','tipo':'reportado',
                          'unidad':'m³/s','valor':10000}]}
        resumen=resumir_represa({'eby':parte},REF)
        self.assertTrue(resumen['reciente'])
        self.assertEqual(resumen['afluencia_prevista'],39000)
        self.assertIsNone(resumen['llegada_local'])
        vencido=resumir_represa({'eby':{**parte,'fecha_informe':'2026-10-14'}},REF)
        self.assertFalse(vencido['reciente'])
        self.assertIsNone(vencido['afluencia_prevista'])

    def test_smn_parcial_o_cancelacion_incierta_no_confirma_ausencia(self):
        self.assertTrue(resumir_smn(localidad(),cap(),REF)['completo'])
        for cambio in ({'fallos':1},{'truncado':True},{'replacements_no_confirmados':1},
                       {'fechas_no_confirmadas_locales':1},
                       {'fecha_feed':REF-timedelta(hours=25)},{'filas':None}):
            with self.subTest(cambio=cambio):
                resumen=resumir_smn(localidad(),{**cap(),**cambio},REF)
                self.assertFalse(resumen['completo'])
                self.assertNotIn('Sin avisos',resumen['estado'])

    def test_smn_avisos_locales_con_area_y_ventana_verificadas(self):
        doc=aviso()
        datos={**cap(),'filas':[doc]}
        resumen=resumir_smn(localidad(),datos,REF)
        self.assertEqual(len(resumen['avisos']),1)
        self.assertEqual(resumen['avisos'][0]['fin'],doc['hasta'])
        otro={**localidad(),'localidad':'Campana centro','partido':'Campana'}
        self.assertEqual(resumir_smn(otro,datos,REF)['avisos'],[])
        doc['poligonos']=[[(0,0),(0,1),(1,0)]]
        doc['nodos']=[]
        self.assertEqual(resumir_smn(localidad(),datos,REF)['avisos'],[])

    def test_smn_vigencia_ausente_exige_verificacion_aunque_feed_este_al_dia(self):
        for campo,valor in [('hasta',None),('emision',REF+timedelta(hours=1)),
                            ('hasta',REF-timedelta(hours=2))]:
            with self.subTest(campo=campo,valor=valor):
                doc={**aviso(),campo:valor}
                resumen=resumir_smn(localidad(),{**cap(),'filas':[doc]},REF)
                self.assertFalse(resumen['completo'])
                self.assertEqual(resumen['avisos'],[])

    def test_riesgo_regional_no_se_reemplaza_por_verde_meteorologico(self):
        decision={'prioridad':2,'nivel_preparacion':'ALERTA PREVENTIVA LOCAL',
                  'motivos':['Índice meteorológico VERDE.','Campana: altura observada alcanza alerta.'],
                  'incertidumbres':['Sin parte local de acceso verificado.']}
        resumen=construir_portada_zc(localidad(),decision,{'emision':REF},observado(),cap(),{},REF)
        self.assertEqual(resumen['prioridad'],2)
        self.assertEqual(resumen['lluvia']['nivel'],'VERDE')
        self.assertEqual(resumen['localidad'],'Zárate centro')
        self.assertIn('regional',resumen['alcance_estado'])
        self.assertIn('Campana',resumen['causa'])
        self.assertIsNone(resumen['orden_evacuacion'])
        self.assertIsNone(resumen['llegada_crecida'])
        self.assertTrue(resumen['faltantes'])

    def test_ausencia_de_evaluacion_no_es_vigilancia_baja(self):
        resumen=construir_portada_zc(localidad(),referencia=REF)
        self.assertIsNone(resumen['prioridad'])
        self.assertFalse(resumen['rio']['vigente'])
        self.assertFalse(resumen['smn']['completo'])


if __name__ == '__main__':
    unittest.main()
