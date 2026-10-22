# Alerta Zárate–Campana · ZC 1.9.1

Herramienta experimental de apoyo a decisiones para Zárate, Campana y referencias del Delta. Integra lluvia modelada, suelo y escurrimiento, alertas SMN, radar SINARAME, alturas y pronósticos INA, Prefectura y contexto de la cuenca del Paraná.

[Abrir Alerta Zárate–Campana](https://alerta-zarate-campana.streamlit.app/)

## Corrección visual 1.9.1

El mapa de referencias utiliza dibujo 2D con Leaflet incluido en la aplicación. Conserva los puntos y sus explicaciones aunque el navegador no pueda usar WebGL o falle el fondo de OpenStreetMap. La vista se ajusta a las diez referencias locales; mantiene el significado meteorológico de sus colores y no modifica la preparación regional.

## Cambios de la versión 1.9.0

El estado local y las cifras de lluvia y río aparecen antes de los detalles de conexión. Los motivos repetidos se agrupan sin ocultar las localidades afectadas ni las señales críticas. Cada cifra conserva su fecha, fuente y estado de vigencia junto al valor.

Para Zárate se incorpora la medición de la estación automática **Paraná Las Palmas - Zárate**, serie INA **29437**, cuando el informe compartido y la observación están vigentes. Se mantiene separada de la escala del puerto (serie 40). Campana conserva su propia lectura (41); no se le asigna el dato de Zárate. Esta incorporación no rebaja el estado de preparación ni traslada referencias de alerta entre estaciones. Ver [evidencia hidrométrica](docs/HIDROMETRIA_ZARATE_20261018.md).

El lector distingue informe actualizado, datos parciales, comprobación, control antiguo y verificación fallida. Cada sitio usa su propio registro público; ZC no presenta un control ALA como prueba de actividad local.

## Qué muestra primero la versión 1.9.0

**Usar mi ubicación** permite elegir automáticamente una referencia cercana, con permiso del navegador. El cálculo queda en el navegador: la app recibe sólo el identificador de una referencia pública, una distancia aproximada y estados de la ayuda. El selector manual siempre está disponible y una elección manual posterior se respeta, aunque llegue tarde una respuesta de ubicación. Con un permiso ya concedido puede realizarse una consulta automática por sesión; no hay seguimiento continuo.

La proximidad no confirma pertenencia a un partido ni cobertura exacta de una calle, isla o lote. Si la precisión no alcanza, la ubicación está demasiado alejada o falla el permiso, la selección se conserva. Cuando corresponde una referencia cercana de ALA, se ofrece un enlace voluntario con su identificador público. Ver [funcionamiento, privacidad y pruebas de ubicación](docs/GEOLOCALIZACION.md).

Elegí la localidad al inicio. La portada muestra la preparación regional, las causas que la justifican, la fecha de evaluación y acciones para el hogar o el trabajo rural. Los bloques de lluvia, río, represas y SMN conservan sus fechas y las ausencias de información. Una causa de Campana sigue identificada como tal aunque se elija una referencia meteorológica de Zárate.

La lluvia indica desde qué hora se cuentan las próximas 24 y 72 horas. La consulta y el cálculo no se anuncian como emisión de la corrida meteorológica. Una lectura local de río de más de seis horas pasa a ser antecedente y no se muestra en la métrica de altura actual. Alerta local y Modelo de inundaciones reutilizan la misma consulta INA y Prefectura.

Las consultas incompletas de SMN no confirman ausencia de avisos. La perspectiva trimestral conserva su fecha de emisión y los meses cubiertos; que incluya octubre no acredita una edición de octubre ni un pronóstico para noviembre o diciembre.

Ver [auditoría conjunta del 17/10/2026](docs/AUDITORIA_SAT_20261017.md).

## Actualización independiente de Zárate–Campana

La página consulta sus diez referencias y sus fuentes INA directamente, con un respaldo público propio. El proceso `.github/workflows/zc-datos.yml` publica en `zc-datos-state` de este repositorio:

- `red_integrada.json`: diez referencias ZC, observaciones y pronósticos locales con sus fechas.
- `meteorologia_zc_ecmwf.json`: captura completa del modelo para la página.
- `datos_status.json`: estado del actualizador de datos ZC, separado del monitor y de los avisos ALA.

La cadencia objetivo es de diez minutos. La captura se consulta por localidad, con presupuesto de tiempo y recuperación por subpartes ante tiempos de espera. Cada descarga completa conserva variables, unidades, coordenadas y hora original. La hidrometría se consulta de forma independiente y se reutiliza la captura para producir las cifras de lluvia, evitando otra descarga igual.

Los archivos se publican juntos en un commit y se confirma su contenido y la rama vigente. Si falla la captura completa se mantiene el archivo anterior sin renovar su fecha; el informe puede publicar las variables disponibles y el fallo local. Una respuesta parcial no reemplaza una captura completa.

El estado distingue **archivo descargado** de **cobertura meteorológica completa**: esta última exige lluvia previa de siete días, lluvia futura de 72 horas, escurrimiento previo de 72 horas y humedad reciente de al menos tres capas. Las variables nulas no cuentan como cobertura y los errores hidrométricos se informan por separado. La fecha de consulta nunca se presenta como emisión del modelo.

Los errores numéricos se aíslan por hora y por horizonte. Por ejemplo, una precipitación negativa del día 13 no elimina las primeras 72 horas válidas; queda sin interpretar en el período afectado. Si el valor inválido está dentro de una ventana necesaria para el índice, esa ventana y el índice quedan sin datos, no en cero.

ALA tiene su propio proceso, su cola y sus 48 puntos en `Alerta-Litoral/ala-monitor-state`. Una falla de cualquiera de las dos aplicaciones no bloquea el actualizador de la otra. Los enlaces entre páginas permiten navegar; no trasladan el estado ni acreditan cobertura en la otra región. Los informes históricos de 58 puntos siguen siendo legibles.

Prueba de consulta sin escrituras ni avisos:

```bash
python publicar_datos_zc.py --dry-run --export-red red_zc_revision.json
```

El actualizador no carga `app.py`, no usa el SQLite de avisos ni lee credenciales de Telegram. Su estado describe la disponibilidad de datos, no una evaluación de envíos. Los datos fluviales antiguos y las horas sin confirmar siguen señalados; la publicación no los convierte en telemetría en vivo.

La solapa **Modelo de inundaciones** muestra variables atmosféricas por horizonte, previsiones fluviales, fechas, horas disponibles y limitaciones. Una fuente fallida no elimina variables válidas de otras fuentes. Un valor ausente se conserva como desconocido y no se convierte en cero.

Los horizontes atmosféricos son corto (0–72 h), mediano (días 4–7) y extendido (días 8–15). Se presenta únicamente la cobertura publicada, sin prolongar un pronóstico más corto. La perspectiva trimestral SMN describe tendencias del período; no determina una probabilidad local de inundación ni anticipa una tormenta puntual.

Las escalas de puerto conservan las observaciones INA 40 (Zárate) y 41 (Campana). La estación automática 29437 se agrega como referencia separada en la portada, las fichas de alturas y la red común. Los metadatos INA identifican a 29437 y al pronóstico 29534 en la misma estación 5907, unidad y cero; ese vínculo no equivale a validar un modelo de inundación. No se confirmó la equivalencia de los puertos 40/41 con los pronósticos 29534/3405; sus umbrales no se trasladan entre escalas ni a la cota del terreno. La lectura automática es información adicional y no modifica por sí sola el estado de preparación.

Cuando falla la consulta actual, las referencias documentales guardadas se muestran con sus fechas originales y su condición de archivo. No acreditan alturas actuales ni generan alertas. Los umbrales de Prefectura e INA se mantienen identificados por fuente.

## Uso y validación

El índice meteorológico y el modelo de inundaciones siguen siendo experimentales. Los pesos y umbrales requieren validación con episodios locales y controles negativos documentados. El color meteorológico no descarta una crecida, una sudestada o un riesgo local.

Los puntos son referencias para celdas del modelo, no estaciones instaladas ni polígonos de barrios. Las rutas, refugios, capacidades sanitarias y partes locales requieren fuentes y vigencia verificadas. La página no acredita inventarios municipales completos ni emite órdenes oficiales de evacuación.

## Telegram

**Telegram de Zárate–Campana permanece pendiente**, según la decisión del proyecto. El actualizador de datos independiente no crea un bot, no agrega destinatarios y no activa avisos automáticos locales. No se debe copiar el SQLite del canal ALA a este repositorio.

## Archivos y ejecución

La aplicación publicada usa `app.py`, `red_integrada.py`, `hidrometria_local.py`, `portada_zc.py`, `ubicacion_local.py` y `requirements.txt` en la raíz. Al actualizarla, subí también la carpeta completa `ubicacion_local_frontend/`, incluidos su catálogo, HTML, JavaScript y CSS locales. Conservá los demás módulos y archivos de soporte existentes. No publiques credenciales en código o documentos.

`.github/workflows/zc-validacion.yml` ejecuta las pruebas de datos y presentación en cada cambio, con permisos de lectura. Después de superarlas en la rama principal, un trabajo separado publica los datos locales sin avisos. `.github/workflows/zc-datos.yml` mantiene la actualización programada, con permisos de escritura sobre este repositorio y sin credenciales de Telegram. Ambos escritores comparten una cola propia de ZC. El archivo `workflows/zc-monitor.yml` permanece fuera de `.github/workflows`; los envíos locales siguen desactivados.

Para ejecutar las pruebas de vigencia, fuentes y selección de localidad, después de instalar las dependencias:

```bash
python -m unittest discover -s tests -v
```

Para abrir el panel local:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```
