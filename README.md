# A.L.A. · Zárate–Campana

Adaptación de Alerta Litoral Agro para los partidos de Zárate y Campana, Buenos Aires. Conserva el panel meteorológico, el índice experimental, las recomendaciones, el mapa, el pronóstico, las herramientas de fuentes y la vigilancia de Telegram de A.L.A.

## Publicar como una aplicación nueva en Streamlit

1. Descomprimí este paquete y creá un **repositorio nuevo** en GitHub, por ejemplo `alerta-zarate-campana`.
2. Subí **todos los archivos** del paquete respetando las carpetas. `app.py`, `hydrology_zc.py`, `monitor.py`, `requirements.txt` y `requirements_monitor.txt` van en la raíz. El workflow va en `.github/workflows/zc-monitor.yml`.
3. En Streamlit Community Cloud elegí **Create app**, el nuevo repositorio, su rama principal y `app.py`. Elegí Python **3.12**.
4. Publicá la aplicación con un nombre propio. El nombre `alerta-zarate-campana` es una sugerencia; su disponibilidad debe comprobarse al publicar.

Para probarla en tu computadora:

```bash
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

La aplicación del Litoral y esta adaptación tienen datos y registros separados. No copies el registro de alertas del Litoral al proyecto nuevo.

## Qué representa el semáforo

El semáforo **VERDE / AMARILLO / ROJO** resume el índice meteorológico experimental de A.L.A. El índice se basa en precipitación modelada reciente y futura, humedad modelada del suelo y runoff. Sus umbrales heredados **no están calibrados ni validados históricamente para estos partidos**. No es una probabilidad de inundación ni un nivel oficial del SMN.

Los puntos son referencias geográficas aproximadas para consultar el modelo. No representan estaciones instaladas, polígonos de barrios ni cobertura completa de cada partido. La aplicación conserva el endpoint ECMWF de A.L.A.; no presupone una resolución de 9 km que esta consulta no permite confirmar. Los puntos cercanos pueden compartir la celda devuelta por el modelo y sus datos. En el Delta, la humedad terrestre modelada no describe el nivel de los canales.

Los datos faltantes no se convierten en cero ni en verde. Las fallas de SMN e INA se muestran como información no verificada. Las rutas dibujadas no acreditan transitabilidad; los refugios y la capacidad sanitaria requieren confirmación municipal.

## Río y sudestada

La sección del río consulta los pronósticos experimentales del INA para **Zárate y Campana**, con fecha de emisión, serie y corrida. Sólo muestra horas futuras disponibles dentro de las próximas 96 horas. Si la corrida tiene más de seis horas, señala el atraso. El máximo mostrado corresponde al período disponible, que puede ser menor de cuatro días.

Las alturas de cada escala no son cotas del terreno ni profundidad de inundación en barrios. Las bandas se reproducen como las publica INA. No se importan umbrales de otras estaciones ni se emite una orden de evacuación desde estos pronósticos. La consulta de alturas observadas se valida por identidad de serie y unidad; puede estar indisponible aunque el pronóstico funcione.

**Un semáforo verde de lluvia no descarta riesgo fluvial, mareológico o de sudestada.** El panel INA queda separado del índice meteorológico. El SHN se incluye como contexto del estuario; sus estaciones no se presentan como mediciones locales.

## Telegram y vigilancia con la página cerrada

El paquete incluye un monitor programable de GitHub Actions, equivalente al de A.L.A. Se evalúa al minuto 17 de cada hora. La entrega de los archivos no activa la programación ni configura las credenciales.

En el **repositorio nuevo**, abrí Settings → Secrets and variables → Actions y agregá:

| Nombre | Valor |
| --- | --- |
| `TELEGRAM_BOT_TOKEN` | Token de tu bot, sólo en Secrets |
| `TELEGRAM_CHAT_ID` | Identificador del chat o `@nombre_del_canal` |

El bot debe tener acceso al destino. Si usás un canal, debe poder publicar allí. Podés usar el mismo bot; cada mensaje identifica Zárate–Campana. Para separar los avisos a los usuarios, configurá un chat o canal propio.

En **Actions → Alerta Zárate–Campana - vigilancia → Run workflow**, hacé primero una ejecución con `dry_run` activado. Comprueba datos sin enviar mensajes ni modificar el registro. Para iniciar la vigilancia, ejecutá otra vez con `dry_run` desactivado.

La primera evaluación válida establece una referencia, sin reenviar episodios rojos ya presentes. Luego avisa nuevos cambios a rojo y actualizaciones que cumplen las reglas heredadas de A.L.A. Guarda la reserva en GitHub antes de enviar para evitar duplicaciones entre controles. Los resultados inciertos no se reenvían automáticamente. `SIN DATOS` no cierra episodios.

El registro se guarda en la rama **`zc-monitor-state`**. Conservá esa rama. Si el repositorio es público, en **Secrets de Streamlit** agregá:

```toml
ALA_MONITOR_REPOSITORY = "tu_usuario/alerta-zarate-campana"
```

Este nombre de configuración se conserva por compatibilidad con A.L.A.; el valor debe apuntar al **repositorio nuevo**. El panel sólo confirma vigilancia con un informe reciente. Si el repositorio es privado, comprobá los controles directamente en Actions.

El monitor automático evalúa **únicamente el índice meteorológico ECMWF**. No envía alertas automáticas de río, sudestada, SMN ni capas cargadas en el navegador. La página puede probar el envío manual si configurás también el bot y el chat en Secrets de Streamlit. No publiques tokens en archivos ni capturas.

GitHub Actions puede demorar ejecuciones y su programación no garantiza disponibilidad continua. Confirmá las ejecuciones en Actions y el último control mostrado en la página. La ausencia de un mensaje no confirma ausencia de peligro.

## Fuentes y contactos

Fuentes revisadas para esta adaptación el 12/10/2026:

- [Open-Meteo · ECMWF](https://open-meteo.com/en/docs/ecmwf-api).
- [SMN · alertas oficiales](https://www.smn.gob.ar/alertas).
- [SMN · radar](https://www.smn.gob.ar/radar/).
- [INA · pronóstico local a cuatro días](https://www.ina.gov.ar/alerta/index.php?seccion=10).
- [INA · visualizador hidrológico](https://alerta.ina.gob.ar/).
- [Prefectura · alturas](https://contenidosweb.prefecturanaval.gob.ar/alturas/).
- [SHN · pronóstico mareológico](https://www.hidro.gov.ar/oceanografia/pronostico.asp).
- [Municipalidad de Zárate · teléfonos útiles](https://zarate.gob.ar/telefonos-utiles/).
- [Municipalidad de Campana · teléfonos útiles](https://www.campana.gob.ar/telefonos-utiles/).

Defensa Civil **103**, Bomberos **100**, Policía **911**. Campana: SAME **107**. Consultá a los municipios por recorridos, centros habilitados y necesidades de evacuación.

La adaptación es un prototipo de apoyo a decisiones. Las advertencias y órdenes oficiales tienen prioridad.
