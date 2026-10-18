# Alerta Zárate–Campana · ZC 1.8.0

Herramienta experimental de apoyo a decisiones para Zárate, Campana y referencias del Delta. Integra lluvia modelada, suelo y escurrimiento, alertas SMN, radar SINARAME, alturas y pronósticos INA, Prefectura y contexto de la cuenca del Paraná.

[Abrir Alerta Zárate–Campana](https://alerta-zarate-campana.streamlit.app/)

## Qué muestra primero la versión 1.8.0

**Usar mi ubicación** permite elegir automáticamente una referencia cercana, con permiso del navegador. El cálculo queda en el navegador: la app recibe sólo el identificador de una referencia pública, una distancia aproximada y estados de la ayuda. El selector manual siempre está disponible y una elección manual posterior se respeta, aunque llegue tarde una respuesta de ubicación. Con un permiso ya concedido puede realizarse una consulta automática por sesión; no hay seguimiento continuo.

La proximidad no confirma pertenencia a un partido ni cobertura exacta de una calle, isla o lote. Si la precisión no alcanza, la ubicación está demasiado alejada o falla el permiso, la selección se conserva. Cuando corresponde una referencia cercana de ALA, se ofrece un enlace voluntario con su identificador público. Ver [funcionamiento, privacidad y pruebas de ubicación](docs/GEOLOCALIZACION.md).

Elegí la localidad al inicio. La portada muestra la preparación regional, las causas que la justifican, la fecha de evaluación y acciones para el hogar o el trabajo rural. Los bloques de lluvia, río, represas y SMN conservan sus fechas y las ausencias de información. Una causa de Campana sigue identificada como tal aunque se elija una referencia meteorológica de Zárate.

La lluvia indica desde qué hora se cuentan las próximas 24 y 72 horas. La consulta y el cálculo no se anuncian como emisión de la corrida meteorológica. Una lectura local de río de más de seis horas pasa a ser antecedente y no se muestra en la métrica de altura actual. Alerta local y Modelo de inundaciones reutilizan la misma consulta INA y Prefectura.

Las consultas incompletas de SMN no confirman ausencia de avisos. La perspectiva trimestral conserva su fecha de emisión y los meses cubiertos; que incluya octubre no acredita una edición de octubre ni un pronóstico para noviembre o diciembre.

Ver [auditoría conjunta del 17/10/2026](docs/AUDITORIA_SAT_20261017.md).

## Red integrada Litoral–Zárate–Campana

Las dos aplicaciones tienen una solapa **Red integrada** que consulta el mismo informe público: `red_integrada.json` en la rama `ala-monitor-state` del repositorio Alerta-Litoral.

El informe reúne los **48 puntos del Litoral y 10 referencias meteorológicas de Zárate–Campana**, estaciones y pronósticos fluviales oficiales disponibles y reportes de represas. Conserva fechas, cobertura y fuentes. Los puntos cercanos pueden representar la misma celda meteorológica.

El monitor existente de ALA prepara el informe común después de guardar su evaluación regional. La consulta adicional de Zárate–Campana no incorpora nuevos candidatos ni destinatarios a Telegram. Cada aplicación conserva sus criterios y registros regionales; el informe común no activa una orden de evacuación.

Un informe con más de 3 horas se señala como vencido. Las alturas y corridas locales de Zárate–Campana también se revisan con un máximo de 6 horas; la fecha de generación del informe no renueva una lectura antigua. No se suman caudales de estaciones sucesivas ni se calcula una hora de llegada desde las compuertas.

Para actualizar, incluí el mismo `red_integrada.py` en la raíz de ambos repositorios. ALA también requiere su `monitor.py` actualizado. Esta prueba se ejecuta **en el repositorio Alerta-Litoral**, que produce el informe común:

```bash
python monitor.py --dry-run --export-red red_integrada_revision.json
```

[Abrir Alerta Litoral Agro](https://alerta-litoral-agro.streamlit.app/) · [Abrir Alerta Zárate–Campana](https://alerta-zarate-campana.streamlit.app/)

## Modelo local y datos disponibles

La solapa **Modelo de inundaciones** muestra variables atmosféricas por horizonte, previsiones fluviales, fechas, horas disponibles y limitaciones. Una fuente fallida no elimina variables válidas de otras fuentes. Un valor ausente se conserva como desconocido y no se convierte en cero.

Los horizontes atmosféricos son corto (0–72 h), mediano (días 4–7) y extendido (días 8–15). Se presenta únicamente la cobertura publicada, sin prolongar un pronóstico más corto. La perspectiva trimestral SMN describe tendencias del período; no determina una probabilidad local de inundación ni anticipa una tormenta puntual.

Las observaciones locales INA corresponden a las series 40 (Zárate) y 41 (Campana). Los pronósticos locales corresponden a las series 29534 y 3405. No se confirmó documentalmente la equivalencia vertical entre observaciones y pronósticos, por lo que no se comparan sus valores con los umbrales de las series observadas ni con la cota del terreno.

Cuando falla la consulta actual, las referencias documentales guardadas se muestran con sus fechas originales y su condición de archivo. No acreditan alturas actuales ni generan alertas. Los umbrales de Prefectura e INA se mantienen identificados por fuente.

## Uso y validación

El índice meteorológico y el modelo de inundaciones siguen siendo experimentales. Los pesos y umbrales requieren validación con episodios locales y controles negativos documentados. El color meteorológico no descarta una crecida, una sudestada o un riesgo local.

Los puntos son referencias para celdas del modelo, no estaciones instaladas ni polígonos de barrios. Las rutas, refugios, capacidades sanitarias y partes locales requieren fuentes y vigencia verificadas. La página no acredita inventarios municipales completos ni emite órdenes oficiales de evacuación.

## Telegram

La conexión común comparte información con ALA. **Telegram de Zárate–Campana permanece pendiente**, según la decisión del proyecto. Esta actualización no crea un bot, no agrega destinatarios y no activa avisos automáticos locales. No se debe copiar el SQLite del canal ALA a este repositorio.

## Archivos y ejecución

La aplicación publicada usa `app.py`, `red_integrada.py`, `portada_zc.py`, `ubicacion_local.py` y `requirements.txt` en la raíz. Al actualizarla, subí también la carpeta completa `ubicacion_local_frontend/`, incluidos su catálogo, HTML, JavaScript y CSS locales. Conservá los demás módulos y archivos de soporte existentes. No publiques credenciales en código o documentos.

`.github/workflows/zc-validacion.yml` ejecuta las pruebas de datos y presentación en cada cambio. Tiene permisos de lectura y no recibe credenciales de Telegram. El archivo `workflows/zc-monitor.yml` conserva su ubicación previa fuera de `.github/workflows`; esta versión no activa un monitor local ni envíos.

Para ejecutar las pruebas de vigencia, fuentes y selección de localidad, después de instalar las dependencias:

```bash
python -m unittest discover -s tests -v
```

Para abrir el panel local:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
