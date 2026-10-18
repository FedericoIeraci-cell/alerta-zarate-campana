"""La ficha pública conserva ausencias, fechas, escalas y alcance regional."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from portada_zc import (TZ, construir_portada_zc, hover_meteorologico_zc,
                        resumir_lluvia, resumir_represa, resumir_rio, resumir_smn)

REF = datetime(2026, 10, 17, 18, 0, tzinfo=TZ)


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
