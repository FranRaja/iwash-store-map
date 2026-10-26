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
7. Para recibir un informe por correo en cada ejecución, crear los secretos `MAP_NOTIFICATION_TO`, `MAP_SMTP_USER` y `MAP_SMTP_PASSWORD` en Settings → Secrets and variables → Actions. El primero es el buzón destinatario; el segundo, la cuenta de Google remitente; el tercero, su contraseña de aplicación. No introducir estos valores en el repositorio ni en archivos locales.
8. Después de guardar los secretos, ejecutar manualmente el flujo con `sync_odoo` activado y comprobar el correo recibido. La primera ejecución mensual está programada para el día 1 a las 09:17, hora de Madrid.

La URL base por defecto es https://smart.iwashlaundry.es. Si la instancia requiere un nombre de base de datos, añadir ODOO_DATABASE como secreto de Actions.

## Datos publicados

La consulta lee el filtro guardado Aperturas Iwash (id 25), el nombre comercial, ciudad, provincia, estado y coordenadas. Incluye registros activos de Smart Shops Factory y registros activos sin compañía. Los datos públicos no incluyen identificadores internos, nombres personales, correos, teléfonos, nombres de compañías vinculadas ni coordenadas 0,0.

El generador conserva la dirección y las coordenadas publicadas actualmente para las 60 tiendas que coinciden con el filtro. Los comercios nuevos aparecen sin marcador hasta que tengan coordenadas Odoo válidas. No se publica su calle hasta incorporarla a la lista de ubicaciones verificadas.

La ejecución se cancela si cambia el dominio de la búsqueda guardada, desaparece el filtro, hay un estado ambiguo, se repite un nombre comercial o falta el nombre comercial de una ficha. Así se evita publicar accidentalmente datos fuera del alcance previsto.

Una ficha puede tener calle en Odoo y seguir sin pin si latitud y longitud están a 0,0. El sincronizador actual no lee los campos street/street2 ni geocodifica; para añadir el pin hay que validar y guardar coordenadas en Odoo o en data/locations-overrides.json. No se deben inventar coordenadas.

## Avisos por correo

Después de cada ejecución mensual o manual, el flujo envía un correo con el resultado, los recuentos de tiendas y marcadores, las fichas añadidas, retiradas o modificadas, las fichas sin coordenadas y el enlace al registro de GitHub Actions. Si falla la lectura de Odoo, se informa del error y se conserva la publicación anterior; el listado de coordenadas ausentes se toma de esa última versión cuando está disponible. Los avisos salen incluso si falla la publicación.

El correo requiere los secretos `MAP_NOTIFICATION_TO`, `MAP_SMTP_USER` y `MAP_SMTP_PASSWORD`. El remitente usa SMTP SSL de Gmail (`smtp.gmail.com:465`); `MAP_SMTP_PASSWORD` debe ser una contraseña de aplicación permitida por la cuenta. No guardar claves en el repositorio, los logs o archivos. Si el correo no se puede enviar, el trabajo `notify` falla en Actions; el despliegue puede haberse completado antes de ese fallo.

La ejecución manual con `sync_odoo` desactivado también genera un correo, e indica que se publicó la captura inicial sin consultar Odoo ni calcular cambios.

## Clave de Odoo

La API externa JSON-2 de Odoo 19 requiere una clave Bearer. Odoo limita a tres meses la duración de las claves manuales; por tanto, la clave del secreto debe renovarse antes de caducar y volver a guardarse en GitHub Actions Secrets. La clave nunca se imprime ni se incluye en el artefacto publicado.

## Archivos

- site/: interfaz del mapa.
- data/locations-overrides.json: ubicaciones ya verificadas y publicadas.
- data/initial-stores.json: captura pública mínima revisada del 23/10/2026 para la primera publicación manual.
- scripts/sync_stores.py: consulta Odoo, filtra y prepara la lista pública.
- .github/workflows/publish.yml: publicación mensual y manual.


