# Mapa público de tiendas IWASH

Este repositorio contiene la página estática del mapa, el generador de datos desde Odoo y el flujo de publicación de GitHub Pages.

[Abrir el mapa público](https://franraja.github.io/iwash-store-map/).

## Cómo se actualiza

- El flujo se ejecuta el día 1 de cada mes a las 09:17, hora de Madrid.
- También puede iniciarse manualmente desde la pestaña Actions con Run workflow.
- Los cambios en main se publican al ejecutar el flujo manualmente o en la siguiente ejecución mensual.
- Si la lectura de Odoo falla, el flujo se detiene antes de publicar y la página desplegada conserva su versión anterior.
- La ejecución manual permite desactivar `sync_odoo` para publicar exclusivamente la captura inicial revisada del 23/10/2026. Esta opción no se utiliza en las ejecuciones mensuales y no reemplaza una actualización fallida desde Odoo.

## Configuración inicial

1. En Settings → Pages, seleccionar GitHub Actions como fuente de publicación.
2. Crear una clave para una cuenta de integración con el acceso de solo lectura mínimo necesario para las fichas del mapa y guardarla directamente como secreto `ODOO_API_KEY` en Settings → Secrets and variables → Actions.
3. Si la instancia lo requiere, guardar el nombre de base de datos como secreto `ODOO_DATABASE`.
4. No guardar la clave en el repositorio, en un archivo, en la URL de Odoo ni en registros.
5. Ejecutar el flujo manualmente con `sync_odoo` activado y comprobar el despliegue. Para la publicación inicial antes de disponer de clave, desactivarlo de forma expresa; los datos conservarán la fecha de la captura revisada.
6. Sustituir una sola vez el iframe de la página de lavanderías de Odoo para que apunte a la URL de GitHub Pages.
7. Para recibir un informe por correo en cada ejecución, crear los secretos `MAP_NOTIFICATION_TO`, `MAP_SMTP_USER` y `MAP_SMTP_PASSWORD` en Settings → Secrets and variables → Actions. El primero es el buzón o los buzones destinatarios (separados por comas); el segundo, la cuenta de Google remitente; el tercero, su contraseña de aplicación. No introducir estos valores en el repositorio ni en archivos locales.
8. Después de guardar los secretos, ejecutar manualmente el flujo con `sync_odoo` activado y comprobar el correo recibido. La primera ejecución mensual está programada para el día 1 a las 09:17, hora de Madrid.

La URL base por defecto es https://smart.iwashlaundry.es. Si la instancia requiere un nombre de base de datos, añadir ODOO_DATABASE como secreto de Actions.

## Datos publicados

La consulta lee el filtro guardado Aperturas Iwash (id 25), el nombre comercial, ciudad, provincia, estado, dirección postal y coordenadas. Incluye registros activos de Smart Shops Factory y registros activos sin compañía. Los datos públicos no incluyen identificadores internos, nombres personales, correos, teléfonos, nombres de compañías vinculadas ni coordenadas 0,0.

Odoo no guarda las coordenadas de las 64 tiendas. Los pines ya publicados se conservan en `data/locations-overrides.json`. Para tiendas sin coordenadas, el flujo consulta CartoCiudad (IGN-CNIG) buscando la calle y el número en `q`, y aplica el código postal por separado como filtro. Si la segunda línea de Odoo nombra un recinto, también consulta ese nombre; solo acepta el punto aproximado si el nombre del candidato aparece en esa dirección. Guarda los resultados aceptados en el mismo archivo y los publica en esa ejecución. La acción no escribe coordenadas en Odoo.

La ejecución se cancela si cambia el dominio de la búsqueda guardada, desaparece el filtro, hay un estado ambiguo, se repite un nombre comercial o falta el nombre comercial de una ficha. Así se evita publicar accidentalmente datos fuera del alcance previsto.

Solo se acepta automáticamente un portal que coincida con el código postal, municipio, calle y número de Odoo. Si el resultado es un punto de referencia de un recinto (por ejemplo, un centro comercial o complejo), se añade con ese carácter aproximado y el correo lo marca para revisión. Si no hay coincidencia suficientemente precisa, la tienda sigue sin pin y el motivo aparece en el correo; el intento se conserva y se reintenta cada 90 días o cuando cambie la dirección de Odoo. No se inventan coordenadas.

CartoCiudad es el servicio oficial del IGN-CNIG y permite uso comercial gratuito. El mapa indica su autoría con la licencia CC BY 4.0 SCNE. No se necesita una clave adicional para geocodificar.

## Avisos por correo

Después de cada ejecución mensual o manual, el flujo envía un correo con el resultado, los recuentos de tiendas y marcadores, los pines añadidos por geocodificación, las fichas añadidas, retiradas o modificadas, las direcciones pendientes o aproximadas y el enlace al registro de GitHub Actions. Si falla la lectura de Odoo, se informa del error y se conserva la publicación anterior; el listado de coordenadas ausentes se toma de esa última versión cuando está disponible. Los avisos salen incluso si falla la publicación.

El correo requiere los secretos `MAP_NOTIFICATION_TO`, `MAP_SMTP_USER` y `MAP_SMTP_PASSWORD`. El remitente usa SMTP SSL de Gmail (`smtp.gmail.com:465`); `MAP_SMTP_PASSWORD` debe ser una contraseña de aplicación permitida por la cuenta. No guardar claves en el repositorio, los logs o archivos. Si el correo no se puede enviar, el trabajo `notify` falla en Actions; el despliegue puede haberse completado antes de ese fallo.

La ejecución manual con `sync_odoo` desactivado también genera un correo, e indica que se publicó la captura inicial sin consultar Odoo ni calcular cambios.

## Clave de Odoo

La API externa JSON-2 de Odoo 19 requiere una clave Bearer. Odoo limita a tres meses la duración de las claves manuales; por tanto, la clave del secreto debe renovarse antes de caducar y volver a guardarse en GitHub Actions Secrets. La clave nunca se imprime ni se incluye en el artefacto publicado.

## Archivos

- site/: interfaz del mapa.
- data/locations-overrides.json: coordenadas conservadas, resultados aceptados y direcciones pendientes de geocodificación.
- data/initial-stores.json: captura pública mínima revisada del 23/10/2026 para la primera publicación manual.
- scripts/sync_stores.py: consulta Odoo, filtra y prepara la lista pública.
- .github/workflows/publish.yml: publicación mensual y manual.


