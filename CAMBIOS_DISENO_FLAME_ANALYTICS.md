# FLAME ANALYTICS — adaptación visual del motor OCEANPIXELS

## Qué se hizo

Se conservó este proyecto como aplicación base. El motor Python, el dataset `data/experiments.csv`, la recuperación de evidencia, las reglas de clasificación, las rutas API y el flujo de interpretación permanecen en sus archivos originales.

Se aplicó una capa visual inspirada en la interfaz FLAME ANALYTICS V22:

- Identidad de marca FLAME ANALYTICS en la barra superior.
- Hero “Beyond the flame.” manteniendo el texto explicativo del motor.
- Esfera azul orgánica decorativa con movimiento autónomo y respuesta suave al cursor y al scroll.
- Fondo espacial oscuro, detalles azul hielo/cian, tipografías DM Sans y Space Grotesk.
- Estilo actualizado para navegación, formularios, botones, filtros, tablas, paneles y gráficos.
- Los gráficos Vega conservan sus datos y especificaciones; solo se ajustó su tema visual.

## Archivos visuales añadidos o modificados

- `web/index.html`: carga la capa visual y agrega el SVG decorativo de la esfera.
- `web/app.css`: se conserva como hoja de estilos base.
- `web/skin.css`: nueva capa de diseño FLAME ANALYTICS.
- `web/skin.js`: animación decorativa de la esfera; no interviene en las consultas ni en el estado del motor.
- `web/app.js`: se conserva el flujo original; únicamente se define un tema oscuro para las visualizaciones Vega.
- `flame/theme.py`: actualiza el nombre de marca y el encabezado visual, manteniendo el subtítulo científico y los indicadores reales del motor.

## Cómo ejecutar

En Windows, ejecuta `INICIAR_WEB_WINDOWS.bat`.
En macOS/Linux, ejecuta `INICIAR_WEB_MAC_LINUX.command`.
La interfaz web se abre en `http://localhost:8600`.

## Credenciales

Por seguridad, el archivo `.env` que venía dentro del ZIP original no se incluyó en este paquete porque contenía una clave de API. Crea tu propio `.env` a partir de `.env.example` y utiliza una clave nueva. Si la clave anterior era real, revócala y genera otra en Google AI Studio.

## Validación

Se comprobaron la sintaxis JavaScript (`app.js`, `skin.js`) y la compilación de los módulos Python modificados. No se pudo ejecutar la suite completa de pruebas en este entorno porque faltaba `altair` y el entorno no pudo descargar dependencias de PyPI.
