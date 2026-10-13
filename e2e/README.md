# Pruebas E2E de la interfaz (Playwright)

Recorren el prototipo en un Chromium headless contra el stack real (interfaz, API y base de datos) y comprueban lo que el presentador ve: cifras, estados, textos y permisos.

## Requisitos

- El stack levantado y sano: `docker compose up -d --build` desde la raíz (interfaz en <http://localhost:8080>).
- `DEMO_MODE=true` (valor por defecto): las pruebas usan `POST /api/dev/reset` y el simulador.
- Node 22 o superior en el equipo.

## Cómo correrlas

```bash
cd e2e
npm run setup      # una vez: instala Playwright y Chromium dentro de e2e/node_modules
npm test           # toda la suite, a 1366x768 y a 1920x1080
```

Otras formas útiles:

```bash
npx playwright test --project=1366x768            # un solo tamaño
npx playwright test tests/alerts.spec.mjs         # un solo archivo
npx playwright test -g "VEH199"                   # las pruebas cuyo nombre contiene ese texto
npx playwright show-report                        # abre el reporte HTML de la última corrida
BASE_URL=http://localhost:9090 npm test           # si la interfaz está en otro puerto
```

El resultado sale en la consola (reporte `list`) y en `e2e/playwright-report/` (HTML). Si una prueba falla, en `e2e/test-results/` quedan la captura y la traza (`npx playwright show-trace <ruta>/trace.zip`). Ninguna de las dos carpetas se versiona.

**Las pruebas nunca llaman a la IA real:** antes de cada reinicio fijan la IA simulada (`PUT /api/dev/ai` con `pinned`) y al terminar devuelven la configurada en `AI_PROVIDER`.

**Las pruebas reinician la demo** antes de cada caso y al terminar: no las corras mientras alguien presenta. La base de la demo es compartida, por eso hay un solo worker, sin paralelismo y sin reintentos.

## Qué cubre cada archivo

| Archivo | Qué comprueba |
|---|---|
| `ai-switch.spec.mjs` | Conmutador "IA: Groq / Groq (texto) / Simulada" del simulador: estado real, las tres opciones con su ayuda y en una sola línea, Groq y Groq (texto) deshabilitados sin clave con su explicación, cambio en caliente entre los tres modos, "Reiniciar demo" vuelve al proveedor configurado, y quién interpretó cada mensaje y leyó la foto (simulador y consola), incluido el rótulo "Lectura de ejemplo" del modo Groq (texto). No llama a Groq. |
| `shell.spec.mjs` | Las 4 rutas, el menú, el título, el pie exacto, la ruta desconocida, el selector de rol (4 roles y persistencia) y "Reiniciar demo" (aviso, cancelar y efecto real). |
| `simulator-green.spec.mjs` | Caso verde VEH901 con el botón del guion, escribiendo a mano y con respuestas rápidas: saludo, placa, servicio de EOM, foto, lectura, línea de estados y "Lo que falta". |
| `console-green.spec.mjs` | Cola (Verde, $90.000, SLA en cuenta regresiva), detalle (foto, confianza, libro único, "Sin alertas", cálculo en 10 pasos), aprobar en un clic, habilitación con copiar, bitácora y mensaje al conductor. |
| `veh015-typo.spec.mjs` | 24.086 corregido a 34.086, Amarillo con R02 y 1 punto, sin un clic, motivo obligatorio. |
| `veh199-night.spec.mjs` | 11:14 p. m., Rojo con 7 puntos, R05, R08 y R09 con su razón exacta, ajuste con motivo y tope, sugerido original en la bitácora. |
| `rejection.spec.mjs` | Rechazo con motivo, mensaje al conductor, estado Rechazada y segunda decisión imposible (409). |
| `simulator-extra-cases.spec.mjs` | Número no registrado, vehículo que no necesita tanquear (acepta o insiste), cambio de caso y reloj simulado frente a R09. |
| `roles.spec.mjs` | Qué puede y qué no cada rol en consola, alertas, conciliación y tablero, en la pantalla y en la API (403). |
| `alerts.spec.mjs` | Orden por prioridad, plazos y vencidas, VEH129, VEH215, VEH160 (libro único Terpel + GoPass), los tres resultados de revisión con autor, fecha y acción siguiente. |
| `reconciliation.spec.mjs` | Carga del exporte de ejemplo, resumen de filas, VEH023 ($21.250, $16.330, 5,647 galones, $27.783), segunda carga sin duplicados y autorizaciones conciliadas. |
| `rules.spec.mjs` | Catálogo R01 a R14 y V01 a V08, versión 2 con historial, validaciones, solo lectura por rol y efecto real del umbral nuevo. |
| `dashboard.spec.mjs` | Los 9 indicadores con línea base, meta y estado, 66,7 h frente a 10 h, desviaciones abiertas, los tres textos de la decisión y cómo cambian los valores con la actividad. |
| `cross-cutting.spec.mjs` | Con datos cargados y en todas las pantallas: sin desborde horizontal, sin estados crudos ni textos en inglés, formatos es-CO, semáforo con texto, F5 en `/consola/:id`. |
| `robustness.spec.mjs` | El caso verde dos veces seguidas da lo mismo; doble clic no duplica decisiones, habilitaciones, mensajes ni revisiones; dos pestañas a la vez. |
| `demo-script.spec.mjs` | El guion de 3 minutos del README, completo y solo por la interfaz. |
| `hard-to-reach-states.spec.mjs` | Estados que la demo no produce sola: SLA de 10 minutos vencido en la cola y en el detalle, y la decisión "Detener" o "Ajustar" del tablero en sus bordes. Toma la respuesta real de la API y cambia solo los campos que nombra cada prueba. |

`tests/support/fixtures.mjs` tiene lo compartido: el reinicio de la demo antes de cada prueba, los ayudantes para sembrar casos por la API y el **guardián del navegador**, que hace fallar cualquier prueba si aparece un error de JavaScript, un error en la consola o una respuesta HTTP 4xx/5xx que la prueba no haya declarado con `guard.allow(...)`.

## Convenciones

- Sin esperas fijas: todo usa las aserciones con auto-espera de Playwright (`expect(...)`, `expect.poll`).
- Localizadores por rol y texto visible; `data-testid` solo donde no hay un ancla estable.
- Las pruebas no se debilitan para que pasen. Un defecto conocido que no se corrige queda como fallo esperado (`test.fail`) con su motivo.

## Guion de capturas

`npm run demo` (`scripts/demo-flow.mjs`) sigue siendo el recorrido que genera las capturas de `docs/screenshots/`; no forma parte de `npm test`.
