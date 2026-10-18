"""Regresiones de evidencia compartida y de la vigencia publicada por la UI."""
from datetime import datetime, timedelta
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import pandas as pd

from portada_zc import TZ, construir_portada_zc, resumir_rio
from test_portada_zc import aviso, cap, localidad, observado

REF = datetime(2026, 10, 17, 18, 0, tzinfo=TZ)
ROOT = Path(__file__).resolve().parents[1]


def cargar_app():
    spec=importlib.util.spec_from_file_location('_zc_evidence_test_app',ROOT/'app.py')
    modulo=importlib.util.module_from_spec(spec)
    with patch.dict(os.environ,{'ALA_MONITOR_HEADLESS':'1'}), \
            patch('requests.sessions.Session.request',side_effect=AssertionError('Red bloqueada en pruebas')):
        spec.loader.exec_module(modulo)
    return modulo


class EvidenciaAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=cargar_app()

    def test_semaforos_del_mismo_punto_vencen_juntos(self):
        nodo=self.app.NODOS[0]
        actual={**nodo,'indice':10.,'estado_datos':'OK','cobertura_meteorologica':True,
                'actualizado':REF.strftime('%d/%m/%Y %H:%M')}
        with patch.object(self.app,'ahora',return_value=REF):
            fila=self.app.integrar_semaforo(pd.DataFrame([actual])).iloc[0]
            self.assertEqual(fila['nivel'],'VERDE')
            self.assertEqual(fila['nivel_meteorologico'],fila['nivel'])
            actual['actualizado']=(REF-timedelta(hours=13)).strftime('%d/%m/%Y %H:%M')
            fila=self.app.integrar_semaforo(pd.DataFrame([actual])).iloc[0]
            self.assertEqual(fila['nivel'],'SIN DATOS')
            self.assertEqual(fila['nivel_meteorologico'],fila['nivel'])

    def test_snapshot_preserva_cada_serie_y_revalida_la_misma_observacion(self):
        observaciones={}; referencias={'referencias':{}}
        for nombre,config in self.app._zc_hidro_estaciones.items():
            serie=config['observada']
            altura=1.55 if serie==40 else 1.20
            observaciones[nombre]={'serie_id':serie,'df':pd.DataFrame([
                {'fecha':REF-timedelta(hours=1),'observado':altura,'zona_horaria_verificada':True}]),
                'url':f'https://alerta.ina.gob.ar/a5/series/{serie}','error':'','consulta':REF.isoformat()}
            referencias['referencias'][serie]={'unidad':'m','fecha_consulta':REF,
                'vinculo_serie_observada_confirmado':True,'nivel_alerta_m':2.,'nivel_evacuacion_m':2.2}
        pna={'error':'Sin consulta actual','registros':{},'referencia_documental':{
            'registros':{'Zárate':{'altura_m':1.2,'fecha_publicada':'14/OCT/26'}}}}
        snapshot=self.app.snapshot_alturas_locales_zc(observaciones,referencias,pna,REF)
        self.assertIs(snapshot['prefectura'],pna)
        for nombre,config in self.app._zc_hidro_estaciones.items():
            del_modelo=snapshot['resumenes'][nombre]
            de_la_ficha=self.app._resumen_rio_prevencion_zc(nombre,config,
                snapshot['observaciones'][nombre],snapshot['referencias'],REF)
            self.assertEqual(de_la_ficha,del_modelo)
            self.assertEqual(resumir_rio(nombre,de_la_ficha,[],REF)['altura'],del_modelo['altura_m'])
            self.assertIsNone(resumir_rio(nombre,de_la_ficha,[],REF+timedelta(hours=6))['altura'])
        self.assertEqual(snapshot['resumenes']['Zárate']['altura_m'],1.55)
        self.assertEqual(snapshot['resumenes']['Campana']['altura_m'],1.20)

    def test_fuente_wfs_identificada_suple_api_sin_huso_sin_cambiar_serie(self):
        config=self.app._zc_hidro_estaciones['Zárate']
        viejo={'serie_id':40,'dias':7,'df':pd.DataFrame([
            {'fecha':REF-timedelta(minutes=15),'observado':1.10,'zona_horaria_verificada':False}]),'error':''}
        wfs={'serie_id':40,'dias':7,'df':pd.DataFrame([
            {'fecha':REF-timedelta(hours=1),'observado':1.55,'zona_horaria_verificada':True}]),'error':''}
        with patch.object(self.app,'ahora',return_value=REF):
            res=self.app.seleccionar_observaciones_locales_zc(viejo,{'observaciones_por_serie':{40:wfs}},config)
        self.assertIs(res,wfs)
        self.assertEqual(res['serie_id'],40)

    def test_trimestral_conserva_emision_y_periodo_independientes(self):
        doc=self.app.referencias_documentales_zc()['smn_trimestral']
        fallo={'error':'No se recuperó el PDF','referencia_documental':doc}
        octubre=self.app.resumen_trimestral_modelo_zc(fallo,REF)
        self.assertEqual(octubre['estado_documento'],'vigente_iniciado_antes')
        self.assertEqual(octubre['fecha_documento'],'2026-07-31')
        self.assertFalse(octubre['informe_smn_disponible'])
        self.assertTrue(octubre['referencia_documental_disponible'])
        noviembre=self.app.resumen_trimestral_modelo_zc(fallo,REF.replace(month=11))
        self.assertEqual(noviembre['estado_documento'],'vencido')
        self.assertEqual(noviembre['fecha_documento'],octubre['fecha_documento'])
        vigente={'inicio':REF.replace(day=1),'fin':REF.replace(month=12,day=31),
                 'emision':REF.replace(month=9,day=30),'periodo':'octubre–noviembre–diciembre 2026',
                 'consulta':REF,'url':'https://www.smn.gob.ar/documento.pdf'}
        self.assertEqual(self.app.resumen_trimestral_modelo_zc(vigente,REF)['estado_documento'],'vigente_mes_actual')

    def test_cruce_local_que_activa_prioridad_alta_permanece_visible_tras_otro_aviso(self):
        smn={**cap(),'filas':[{**aviso(),'severidad_cap':'Moderate'}]}
        rios=[observado(),{**observado(),'serie_id':41,'nombre':'Campana','altura_m':2.3}]
        meteo={'nivel':'VERDE','completo':True,'vigente':True,'lecturas_validas':True}
        prevencion=self.app.evaluar_prevencion_inundaciones_zc(meteo,smn,rios,{},referencia=REF)
        decision=self.app.construir_decision_cuenca_zc({},prevencion,{},REF)
        self.assertEqual(decision['prioridad'],2)
        portada=construir_portada_zc(localidad(),decision,{'emision':REF},rios[0],smn,{},REF)
        self.assertEqual(portada['prioridad'],2)
        self.assertIn('Campana',portada['causa'])
        self.assertIn('referencia INA de evacuación',portada['causa'])
        self.assertTrue(any('SMN:' in causa for causa in portada['causas']))


if __name__ == '__main__':
    unittest.main()
