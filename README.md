# Prototipo visual: suministro de combustible (Transportes Esivans)

Prototipo para una demo de 3 minutos del flujo principal del MVP: el conductor pide combustible por WhatsApp, un asistente con IA arma la solicitud, el motor de reglas calcula el semáforo y el valor sugerido, el técnico de Control y Monitoreo decide en la consola y todo queda en la bitácora.

**No es el MVP ni una aplicación de producción.** Lo que se muestra funciona de punta a punta contra una API y una base de datos reales, pero con datos ilustrativos y con las integraciones externas simuladas (ver [qué está simulado](#qué-está-simulado-y-qué-es-real)). Todas las pantallas llevan el rótulo "Prototipo con datos ilustrativos | Uso exclusivo del proceso de selección".

## Requisitos

- Docker Desktop (o Docker Engine con Compose v2) encendido. Probado en Windows 11; no usa nada propio de Windows.
- Puertos libres en el equipo: **8080** (interfaz) y **8000** (API). Se cambian con `FRONTEND_PORT` y `BACKEND_PORT`.
- No hace falta internet para la demo ni ninguna clave: el adaptador de IA por defecto es local.
- Solo para regenerar las capturas: Node 22 o superior en el equipo (carpeta `e2e/`).

## Cómo levantarlo

```bash
docker compose up -d --build
```

La primera vez tarda unos minutos (compila Angular dentro de Docker). El backend espera a que la base esté sana, aplica la migración y carga la semilla. Cuando los tres servicios aparecen como `healthy` en `docker compose ps`, abre <http://localhost:8080>.

Para probar desde cero (borra el volumen de la base de este proyecto y nada más):

```bash
docker compose down -v
docker compose up -d --build
```

Pruebas del backend, dentro del contenedor (usan una base aparte, `esivans_test`, y no tocan la demo):

```bash
docker compose exec backend pytest
```

## URLs

| Qué | URL |
|---|---|
| Interfaz (simulador, consola, alertas y tablero) | <http://localhost:8080> |
| Simulador del conductor | <http://localhost:8080/simulador> |
| Consola del técnico | <http://localhost:8080/consola> |
| Alertas del coordinador | <http://localhost:8080/alertas> |
| Tablero del piloto | <http://localhost:8080/tablero> |
| Guía de estilo (componentes) | <http://localhost:8080/guia-estilo> |
| API: documentación OpenAPI | <http://localhost:8000/docs> |
| API: estado | <http://localhost:8000/api/health> |

La interfaz llama a la API por `http://localhost:8080/api/...` (nginx hace de proxy al backend).

## Variables

Sin archivo `.env` todo funciona con los valores por defecto. Para cambiar algo, copia `.env.example` como `.env`.

| Variable | Por defecto | Para qué |
|---|---|---|
| `TZ` | `America/Bogota` | Zona horaria de toda la aplicación |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `esivans`, `esivans`, `esivans_demo` | Base de datos (el puerto no se publica fuera de Docker) |
| `FRONTEND_PORT` | `8080` | Puerto de la interfaz en el equipo |
| `BACKEND_PORT` | `8000` | Puerto de la API en el equipo |
| `AI_PROVIDER` | `mock` | `mock` (local y determinista) o `gemini` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | vacías | Solo con `AI_PROVIDER=gemini` |
| `WHATSAPP_APP_SECRET` | `demo-secret` | Secreto con que se firma y se verifica el webhook (`X-Hub-Signature-256`) |
| `WHATSAPP_VERIFY_TOKEN` | `demo-verify-token` | Verificación del webhook (`GET /api/webhooks/whatsapp`) |
| `DEMO_MODE` | `true` | Habilita `/api/dev/*`: el simulador y "Reiniciar demo" |

## Qué está simulado y qué es real

| Parte | En el prototipo | En el MVP |
|---|---|---|
| WhatsApp | **Simulado con el contrato real.** El simulador llama a `POST /api/dev/simulator/messages`; el backend arma el payload con la forma de la WhatsApp Cloud API, lo firma con HMAC-SHA256 y lo procesa con el mismo handler de `POST /api/webhooks/whatsapp` (verifica la firma sobre el cuerpo crudo y descarta duplicados por el ID del mensaje). Las respuestas se guardan en `outbound_message`. | WhatsApp Cloud API con un número dedicado y plantillas aprobadas |
| Fotos del tablero | Imágenes de ejemplo propias (SVG), una por caso, servidas por un almacenamiento local que simula la Media API | Media API y fotos privadas con URL firmada |
| IA (texto y foto) | `MockProvider`: reglas simples para el texto y la lectura de cada foto en un JSON al lado. Determinista y sin internet. `GeminiProvider` existe pero no se probó contra el servicio | Gemini (API de pago o Vertex AI) detrás del mismo adaptador |
| Motor de reglas, semáforo y valor sugerido | **Real.** R01 a R14 con los umbrales y puntos calibrados, versionados en `rule_version` | Igual |
| Decisión, habilitación y bitácora | **Real.** Una sola decisión por solicitud, motivo obligatorio fuera de la recomendación y `audit_log` de solo inserción (un trigger de PostgreSQL rechaza `UPDATE` y `DELETE`) | Igual |
| Habilitación del chip o la tarjeta | El técnico copia los valores precargados y confirma una referencia. No hay portal del proveedor | Igual en el MVP (manual); por API o RPA en la etapa 2 |
| Conciliación | **Real** sobre un CSV de ejemplo de Terpel: idempotente, cruza con las autorizaciones y evalúa R11 a R14 y el producto | Archivos diarios de Terpel y GoPass |
| EOM, Terpel y GoPass | Semilla escrita a mano: 24 vehículos, 878 tanqueos de 90 días y 1.534 servicios | Integraciones reales |
| Reglas por vehículo (V01 a V08) y rendimiento | Vienen calculados en la semilla | Salen del análisis de 90 días |
| Ingreso y roles | Selector de rol en la barra superior (cabeceras `X-Demo-Role` y `X-Demo-User`). Los permisos sí se validan en la API (403) | SSO (OIDC) con MFA |
| Colas y trabajos en segundo plano | Sin Redis ni Celery: `BackgroundTasks` de FastAPI. Los eventos de dominio solo se registran en la tabla `outbox` | Redis, workers y consumidores de eventos |
| Tablero | 7 indicadores se calculan con la actividad de la demo; integraciones y continuidad son ilustrativos (cada tarjeta lo dice) | Indicadores del piloto con su línea base medida |

## Historias de usuario que cubre

HU-01, HU-02, HU-03, HU-04, HU-07 (ficha técnica y tope en la semilla), HU-09, HU-10, HU-12, HU-13, HU-15 (habilitación manual con valores precargados), HU-16 (conciliación simplificada), HU-17, HU-18, HU-19 y HU-22 (roles simulados). Las demás quedan fuera del prototipo.

Lo que quedó parcial o por fuera de esas historias está en la sección "Lo que no cubre el prototipo" de [`DECISIONES.md`](DECISIONES.md).

## Guion de la demo (3 minutos)

**Antes de empezar:** abre <http://localhost:8080>, deja el rol en "Técnico de Control y Monitoreo" y haz clic en **Reiniciar demo** (arriba a la derecha) y confirma en el aviso. La cola queda vacía. Pon el navegador a pantalla completa (F11); a 1366×768 el detalle de la solicitud necesita un poco de scroll para ver la bitácora.

| # | Tiempo | Qué hacer | Qué decir |
|---|---|---|---|
| 1 | 0:00 a 0:35 | **Simulador del conductor**, caso **VEH901** (ya viene elegido). Clic 4 veces en **Siguiente paso del guion**: saludo, servicio de EOM, foto del tablero y confirmación. | "El conductor escribe que necesita tanquear. El asistente lo reconoce por su número, lo saluda por su nombre, confirma la placa ZZA901 y le propone su servicio de EOM. Envía la foto y solo confirma lo que la IA leyó: 48.352 km y ¼ de tanque. A la derecha se ve la solicitud avanzando de Recibida a En revisión." |
| 2 | 0:35 a 1:15 | Clic en **Ver en la consola**. Mostrar el semáforo verde, la foto, el libro único y el cálculo. Clic en **Aprobar en un clic** → **Confirmar** (la referencia ya viene sugerida). Bajar a la **bitácora**. Clic en **Ver el mensaje al conductor**. | "La solicitud llega en verde, sin alertas, con el valor sugerido de $90.000 y el cálculo paso a paso con la fórmula del instructivo. Se aprueba en un clic. Como en el MVP la habilitación la hace el técnico, la consola le deja los valores listos para el portal del proveedor. Al confirmar, el conductor recibe el valor, Gasolina Corriente, la referencia y la vigencia de 2 horas. La bitácora guarda quién, cuánto, cuándo y con qué versión de reglas." |
| 3 | 1:15 a 1:40 | En el simulador, chip **VEH015**. Clic 3 veces en **Siguiente paso del guion** y luego en la respuesta rápida **Sí, es 34.086**. | "El odómetro es el dato más débil. La foto se lee como 24.086 km, pero su último registro es 33.948: el asistente detecta que es un error de un dígito, propone 34.086 y el conductor lo confirma. Es la regla R02; llega al técnico en amarillo y ya no se aprueba con un clic, pide el motivo." |
| 4 | 1:40 a 2:15 | Chip **VEH199** (el reloj simulado marca 23:14). Clic 4 veces en **Siguiente paso del guion** → **Ver en la consola**. Mostrar las tres razones. Clic en **Ajustar**, escribir `20000`, clic en el motivo sugerido → **Guardar ajuste** → **Confirmar**. | "A las 11:14 de la noche un vehículo de gas pide 6,7 m³ con solo 22 km desde su carga anterior y sin servicios en EOM. Suma 7 puntos y queda en rojo, y cada regla dice por qué: R05, R08 y R09. Ninguna regla bloquea: el técnico decide, pero para ajustar el valor el motivo es obligatorio y el cálculo original queda guardado." |
| 5 | 2:15 a 2:45 | Cambiar el rol a **Coordinador**. Menú **Alertas del coordinador** → pestaña **Conciliación** → **Cargar exporte de ejemplo de Terpel**. Luego pestaña **Vehículos** (el VEH129 es el primero), bajar, elegir **Confirmado** → **Registrar resultado**. | "Al conciliar el archivo del proveedor, las autorizaciones de hace un momento cuadran, y aparece el VEH023: cargó Extra a $21.250 cuando su ficha pide Corriente, que estaba a $16.330 en la misma estación: $27.783 pagados de más. Y por vehículo, el VEH129 suma 8 puntos: rinde 61 % menos que su grupo y tanqueó 102 veces sin servicios en EOM. El coordinador registra el resultado, Confirmado, con su nombre y la fecha, y el sistema le dice la acción que sigue." |
| 6 | 2:45 a 3:00 | Menú **Tablero del piloto**. | "Los nueve indicadores del piloto frente a su línea base y su meta, las desviaciones abiertas y la decisión al cierre de las 6 semanas: ampliar, ajustar o detener. Hoy la gestión suma 66,7 horas al día frente a 24 horas de turnos; con 3 minutos por solicitud baja a 10." |

Notas para el presentador:

- **No hace falta teclear nada** salvo el `20000` del paso 4: el guion de cada caso se avanza con un botón y los motivos y comentarios tienen sugerencias de un clic.
- **El recuadro "Con los valores de hoy aplicaría"** del tablero dice **Ampliar** con la demo recién reiniciada y **Ajustar** después del guion, porque no todas las solicitudes se aprobaron en un clic (la meta es 60 % o más). Es coherente y sirve para explicar que los indicadores se leen juntos.
- **Los tiempos de atención del tablero** salen de lo que tardó el presentador en decidir (segundos); son reales, no ilustrativos.
- La hora que muestran el chat y la consola es la **hora simulada del caso**; la bitácora guarda la hora real.
- En el paso 3 el VEH015 queda en la cola sin decidir (para no gastar tiempo). Si quieres cerrarlo: **Ver en la consola** → **Aprobar con motivo** → motivo sugerido → **Aprobar** → **Confirmar**.
- Casos extra si preguntan: chip **VEH902** (el asistente le explica que no necesita tanquear) y **Sin registro** (número no registrado: pasa al técnico con el motivo). En **Alertas → Reglas y umbrales** solo el Coordinador puede cambiar un umbral y queda una versión nueva; en **Alertas → Vehículos → VEH160** se ve el libro único (GoPass solo calcularía 783 km por galón).

## Cómo reiniciar la demo

- **Desde la interfaz:** botón **Reiniciar demo** (arriba a la derecha, visible con `DEMO_MODE=true`) y confirmar en el aviso. Vacía las solicitudes, restaura las alertas y las reglas a la versión 1 y vuelve a cargar la semilla.
- **Desde la terminal:** `curl -X POST http://localhost:8080/api/dev/reset`
- **El día de la presentación:** la semilla es relativa al día en que se carga (los servicios de EOM "de hoy" y los tanqueos de los últimos 90 días). Si los contenedores quedaron encendidos desde el día anterior, **reinicia la demo antes de presentar** para que la semilla quede con la fecha de hoy.
- **Desde cero:** `docker compose down -v && docker compose up -d --build`.

## Cómo activar Gemini (opcional)

La demo no lo necesita. Para probar la lectura real de fotos y mensajes:

1. Copia `.env.example` como `.env`.
2. Pon `AI_PROVIDER=gemini`, tu clave en `GEMINI_API_KEY` y en `GEMINI_MODEL` un modelo de la familia Flash **tal como aparece en la documentación oficial vigente** (el nombre no está escrito en el código a propósito).
3. `docker compose up -d backend` y revisa `ai_provider` en <http://localhost:8000/api/health>.

Si falta la clave o el modelo, se usa el `MockProvider`. Si Gemini falla o la confianza es baja, el asistente le pide el dato al conductor y la solicitud sigue. Gemini no decide ni calcula el valor: devuelve datos (JSON contra un esquema Pydantic) que el backend valida.

> El `GeminiProvider` usa el SDK oficial `google-genai`, pero **no se probó contra el servicio real** (no había clave en el entorno de desarrollo). Las fotos de ejemplo son dibujos; con Gemini conviene probar con fotos reales de un tablero.

## Capturas y recorrido automático

`docs/screenshots/` tiene las capturas del guion completo a 1366×768 y a 1920×1080 (43 por tamaño, numeradas en orden). Se regeneran con Playwright en modo headless contra el stack levantado:

```bash
cd e2e
npm run setup      # una vez: instala Playwright y Chromium dentro de e2e/node_modules
npm run demo       # recorre el guion, valida y guarda las capturas; reinicia la demo al terminar
npm test           # pruebas E2E de toda la interfaz, a 1366×768 y a 1920×1080 (reinician la demo)
```

`npm run demo` falla (código 1) si hay errores de JavaScript, desborde horizontal, el pie de página no es el esperado o alguna cifra de los casos no coincide.

`npm test` recorre las cuatro pantallas con aserciones sobre cifras, estados, textos y permisos; qué cubre cada archivo y cómo correr una parte está en [`e2e/README.md`](e2e/README.md).

## Estructura

```
docker-compose.yml   db (PostgreSQL 17), backend (FastAPI) y frontend (Angular + nginx)
backend/             app/{requests,ledger,rules,decisions,reconciliation,integrations,dashboard,dev,seed}, alembic/, tests/
frontend/            Angular 22: core/, shared/, layout/ y features/{simulator,console,alerts,dashboard}
e2e/                 Playwright: guion de la demo, capturas y pruebas E2E de la interfaz
docs/screenshots/    capturas revisadas
PLAN.md              hitos
DECISIONES.md        cada decisión con su motivo y lo que no cubre el prototipo
```

La carpeta `referencias/` (los documentos de la prueba) está en `.gitignore`: no se versiona ni se copia dentro del código.
