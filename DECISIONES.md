# Decisiones del prototipo

Cada decisión con su motivo. Es un prototipo para una demo de 3 minutos, no el MVP: cuando hubo que elegir, se prefirió lo más simple que deja el flujo principal funcionando.

## Alcance y arquitectura

| # | Decisión | Motivo |
|---|---|---|
| 1 | Sin Redis ni Celery: el trabajo en segundo plano usa las `BackgroundTasks` de FastAPI. | La arquitectura del informe los tiene, pero para una demo no aportan. El webhook responde 200 de inmediato y la conversación se procesa después de la respuesta, que es el mismo comportamiento que tendría con un worker. |
| 2 | Los eventos de dominio (`RequestReceived`, `DecisionRecorded`, `TransactionImported`, `DeviationDetected`) solo se registran en la tabla `outbox`. | El prompt pide registrarlos; no hay consumidores en el prototipo. Se consultan en `GET /api/dev/outbox`. |
| 3 | Roles simulados con las cabeceras `X-Demo-Role` (technician, coordinator, finance, support) y `X-Demo-User`. | En producción el ingreso es con SSO (OIDC) y MFA. Aquí basta el selector de rol de la interfaz. Sin cabecera, el rol es técnico. |
| 4 | Monolito modular con los módulos del informe (`requests`, `ledger`, `rules`, `decisions`, `reconciliation`, `integrations`), pero los modelos de SQLAlchemy están en un solo archivo (`app/models.py`). | Son 19 tablas pequeñas; un archivo se lee más rápido que seis. La lógica sí está separada por módulo. |
| 5 | Las respuestas son diccionarios armados a mano, no modelos Pydantic de salida. Pydantic se usa en los cuerpos de entrada y en el adaptador de IA. | Menos código para un prototipo. El costo es que `/docs` muestra las rutas y las entradas, pero no el esquema de cada respuesta; el contrato está documentado aparte. |
| 6 | La migración inicial de Alembic se generó con `--autogenerate` y se le agregó a mano el trigger de `audit_log`. | Es la forma estándar y evita escribir 19 tablas a mano. |
| 7 | `audit_log` es de solo inserción y lo refuerza un trigger de PostgreSQL que rechaza `UPDATE` y `DELETE`. | El informe pide una bitácora de solo inserción; así no depende de que el código se porte bien. |
| 8 | `POST /api/dev/reset` vacía las tablas con `TRUNCATE` y vuelve a cargar la semilla. Solo existe con `DEMO_MODE=true`. | Es el botón "Reiniciar demo". Es el único borrado físico del prototipo y solo toca datos ilustrativos; en el producto real ningún dato de dominio se borra físicamente. |
| 9 | El puerto de PostgreSQL no se publica. | Nadie necesita entrar a la base desde fuera y así no choca con otros proyectos del equipo. |

## Hora simulada y semilla

| # | Decisión | Motivo |
|---|---|---|
| 10 | El simulador envía la hora del caso en el campo `timestamp` del mensaje, como lo hace la WhatsApp Cloud API. La solicitud guarda `occurred_at` (hora del caso, la que usan las reglas, por ejemplo R09) y `created_at` (hora real, para la cola y el SLA de 10 minutos). | Permite mostrar el caso de las 11:14 p. m. a cualquier hora sin que el SLA ni la cola se descuadren. |
| 11 | El primer mensaje fija la hora del caso; los siguientes avanzan con el tiempo real transcurrido. | El chat se ve natural y la hora del caso no cambia entre mensajes. |
| 12 | La vigencia de la autorización (2 horas) se guarda en hora real (`expires_at`); el chat, el simulador y el aviso de la consola la muestran en la hora del caso (`expires_at_case_time`). La bitácora guarda la hora real. | La consola dice "Pedida a las 9:40 a. m." (hora del caso), así que la vigencia debe leerse con el mismo reloj; si no, el técnico vería "hasta las 9:36 p. m." y el conductor "hasta las 11:40 a. m." para la misma autorización. |
| 13 | La semilla es relativa al día en que se carga: los servicios de EOM "de hoy" siempre existen y los 90 días de tanqueos terminan ayer. Si el contenedor arranca otro día, la semilla se recarga sola. | Con fechas fijas el caso verde dejaría de ser verde al día siguiente (no tendría servicios hoy). `GET /api/dev/simulator/cases` avisa con `seed_is_stale` si cambió el día con el contenedor encendido. |
| 14 | Semilla determinista, sin azar: 24 vehículos, 878 tanqueos, 1.534 servicios de EOM y 19 alertas. | La demo debe dar siempre lo mismo. |
| 15 | La cola del técnico arranca vacía. | Es más predecible para la demo: lo único que aparece es lo que el presentador acaba de enviar, y no hay solicitudes viejas con el SLA vencido. |
| 16 | Las fotos del tablero son SVG propios (odómetro y medidor de nivel, sin marcas), una por caso, cada una con su lectura en un JSON al lado. El `MockProvider` las reconoce por el SHA-256 de la imagen. | Así la demo no depende de internet ni de un servicio de visión. |
| 17 | En la foto del VEH015 el odómetro marca 34.086 con un reflejo sobre el 3, y la lectura devuelve 24.086. | Muestra el caso del documento (24.086 se corrige a 34.086) con una foto que lo hace creíble. |

## Valores que no vienen en los datos

| # | Decisión | Motivo |
|---|---|---|
| 18 | Capacidad del tanque: 12 gal en gasolina y bicombustible (tanque líquido), 18 gal en diésel liviano, 40 gal en diésel pesado y 14 m³ en gas. | Los datos del caso no la traen. Son valores razonables para vans y camionetas; en el MVP salen de la ficha técnica (HU-07). |
| 19 | Km típicos por servicio en CARIBE COR: 18 km. | EOM no trae km por servicio. Es un valor ilustrativo para que la fórmula se pueda mostrar. |
| 20 | Precios de referencia: Corriente $16.000, Extra $21.250, diésel $11.100 y gas $3.200 por m³. Las estaciones de la semilla tienen precios propios (la del VEH023, $16.330). | Son los del prompt. El valor sugerido usa el de referencia; la conciliación usa el de la estación. |
| 21 | "Fin del turno" = fin del día de la solicitud. Ruta pendiente = servicios de EOM de hoy que empiezan después de la hora de la solicitud. | No hay turnos por vehículo en los datos. |
| 22 | El tope se redondea hacia abajo al múltiplo de $10.000. | El valor siempre es múltiplo de $10.000 y nunca debe pasar del tope. |
| 23 | El rendimiento por vehículo y las reglas V01 a V08 vienen calculados en la semilla; no se recalculan con los tanqueos generados. | En producción salen del análisis de 90 días. Así las cifras de los documentos (VEH129, VEH215) quedan exactas. |

## Reglas y valor recomendado

| # | Decisión | Motivo |
|---|---|---|
| 24 | Motor de reglas en Python puro, sin pandas, portando umbrales y puntos de `fuel/config.py` y `fuel/rules.py` y la clasificación de digitación de `fuel/odometer.py`. Los umbrales se leen de la `rule_version` vigente. | Es lo que pide el prompt, y una solicitud es una sola fila: pandas sobra. |
| 25 | R08 y R09 solo aplican si el vehículo existe en EOM, igual que en `rules.py`. A un vehículo sin EOM (V05) el asistente le pide la justificación en la conversación y llega al técnico. | Fiel al análisis. El VEH015 no tiene servicios en EOM (V05), así que su caso queda en amarillo solo por R02. |
| 26 | R05 y R07 usan como carga la cantidad que pide el conductor si la dice; si no, la sugerida. | En una solicitud todavía no hay carga real. El VEH199 pide 6,7 m³ en su primer mensaje y da exactamente las cifras del documento. |
| 27 | R10 (estación fuera de zona) no se evalúa en la solicitud. | Necesita la estación real, que solo se conoce cuando llega la transacción del proveedor. Aparece como "no evaluada" en el detalle. |
| 28 | En un bicombustible la solicitud es por el tanque líquido (Gasolina Corriente) y su rendimiento en km/gal-eq se usa como km/gal. | Simplifica el cálculo. El MVP manejaría los dos tanques por separado. |
| 29 | Control cruzado: con los km recorridos y el rendimiento se calcula entre cuánto debería tener el tanque. Si el nivel leído se sale de ese rango por más del 15 % de la capacidad, la solicitud queda en amarillo con la razón (0 puntos). | Hace concreto "si no cuadra con el nivel leído" del informe. La tolerancia es amplia porque un medidor no es preciso. |
| 30 | Las inconsistencias (control cruzado, solicitud incompleta, número no registrado, "no necesita tanquear") van con el código `INC` y 0 puntos; ponen el semáforo en amarillo. | El informe dice amarillo "con una inconsistencia entre fuentes" sin sumar puntos. |
| 31 | Se agregaron dos controles de conciliación al catálogo: `C01` (producto distinto al de la ficha) y `C02` (valor distinto al autorizado, más de 5 %), con 2 puntos. | El informe pide conciliar valor y producto, pero no les da código. Tener código permite versionarlos y medir su precisión como a las demás reglas. |
| 32 | La versión de reglas es un número de catálogo: `v1` es la calibración inicial y cada cambio de umbral suma uno. Cada evaluación y cada alerta la guarda. | Basta para mostrar que el cambio queda versionado. |

## Decisión, habilitación y conversación

| # | Decisión | Motivo |
|---|---|---|
| 33 | Aprobar en un clic solo con semáforo verde. En amarillo o rojo, o si el valor cambia, el motivo es obligatorio (422 si falta). Rechazar siempre exige motivo. | Es la regla del informe: ninguna regla bloquea, pero salirse de la recomendación deja rastro. |
| 34 | Una sola decisión por solicitud: restricción única en la base y 409 con quién decidió. | Dos técnicos no pueden autorizar lo mismo. |
| 35 | Tras aprobar o ajustar, la solicitud sigue `in_review` (etapa "Por habilitar") hasta que el técnico confirma la referencia del proveedor; ahí pasa a `authorized` y el conductor recibe valor, producto, referencia y vigencia. | En el MVP la habilitación la hace el técnico (HU-15). No se agregó un estado nuevo para no cambiar los del informe. |
| 36 | Se agregó el estado `cancelled` ("Cerrada sin tanqueo") para cuando a cargar da 0 o menos y el conductor acepta. Si insiste, pasa al técnico en amarillo. | Los estados del informe no cubren ese cierre y `rejected` no sería cierto. |
| 37 | Decidir lo pueden hacer técnico y coordinador; revisar alertas, coordinador y técnico; cargar archivos, finanzas, coordinador y técnico; cambiar umbrales, solo el coordinador. Un intento sin permiso responde 403 y queda en la bitácora. | Sigue la tabla de responsables del informe. |
| 38 | El SLA de 10 minutos se revisa al consultar la cola o la conversación, no con un proceso programado. | Sin worker es lo más simple; el efecto visible es el mismo. |
| 39 | Las respuestas rápidas van como texto y se limitan a 3 por mensaje. | Es el máximo de botones de respuesta de la Cloud API. |
| 40 | Una sola convención de hora en la interfaz y en los mensajes del asistente: `h:mm a. m./p. m.` ("11:40 a. m."). Las excepciones son la razón de R09, que conserva "23:14", y el campo del reloj simulado, que es el control de hora del navegador. | El prompt pide una sola convención. La razón de R09 se deja como la escribe el libro de casos ("tanqueo a las 23:14 sin servicios cercanos") porque es una cifra de los documentos. |
| 48 | Cuando el técnico ajusta el valor, el mensaje de autorización al conductor incluye el motivo; cuando rechaza, también. | HU-04, escenario 3: el conductor recibe el resultado con ese motivo. |

## Conciliación

| # | Decisión | Motivo |
|---|---|---|
| 41 | La importación es idempotente por un hash de proveedor, ID, vehículo, fecha, producto, cantidad y valor. | Cargar el mismo archivo dos veces no duplica nada. |
| 42 | El CSV de ejemplo es una plantilla con fechas relativas (`{{D1}}` = ayer) que `GET /api/dev/samples/terpel` entrega ya resuelta. Además agrega una fila por cada autorización de Terpel hecha en la demo. | Las fechas tienen que caer dentro de la semilla, y así la conciliación "autorizado frente a registrado" tiene algo real que cruzar. |
| 43 | El precio de la Corriente para calcular lo pagado de más por Extra es el de la misma estación ese día; si no vendió, el de referencia. | Es el método del informe. Para el VEH023 da $16.330 y $27.783 pagados de más. |
| 44 | El importador acepta el archivo como `multipart`, como JSON o como CSV en el cuerpo. | Para que la interfaz lo cargue con un botón sin armar un formulario. |

## Adaptador de IA

| # | Decisión | Motivo |
|---|---|---|
| 45 | `MockProvider` por defecto. `GeminiProvider` es opcional y exige `GEMINI_API_KEY` y `GEMINI_MODEL`; el nombre del modelo no está escrito en el código. | El prompt pide no inventar el nombre del modelo. Si falta cualquiera de los dos, se usa el mock. |
| 46 | Si Gemini falla al leer la foto, el asistente le pide el kilometraje al conductor; si falla al interpretar el texto, responde el intérprete local. | La demo y la operación no se pueden detener por la IA. |
| 47 | El `GeminiProvider` no se probó contra el servicio real. | No hay clave en este entorno. En producción se usaría la Gemini API de pago o Vertex AI. |

## Interfaz

| # | Decisión | Motivo |
|---|---|---|
| 49 | Angular 22 (la versión estable que devolvió `npm view @angular/cli version`), compilado dentro de Docker con Node 24 y servido con nginx. | Angular 22 exige Node `^22.22.3` o `^24.15.0`; así nada se instala en el equipo. |
| 50 | nginx resuelve `backend` en cada petición (DNS interno de Docker) y responde 502 si no está. | El frontend arranca aunque el backend todavía no exista, y la pantalla sigue en pie con el aviso "No hay conexión con el servidor". |
| 51 | Sin librería de componentes: estilos propios en CSS global (`.ui-*`) con las variables de color del prompt y Lato autoalojada (`@fontsource/lato`). | Control total del acabado y la misma familia visual de la presentación; la demo no depende de una CDN. |
| 52 | Tamaño base de 15 px, y 16 px desde 1.600 px de ancho; todo en `rem`. | Para que se vea bien proyectado a 1366×768 y a 1920×1080. |
| 53 | Formato es-CO con pipes propios (miles con punto, decimales con coma, pesos sin decimales, `73 %` con espacio no separable y `dd/mm/aaaa`). Un ISO sin zona se interpreta como hora de Bogotá. | Los pipes de Angular no dan exactamente ese formato. |
| 54 | Todos los roles ven las cuatro pantallas; lo que cambia son las acciones. Deciden técnico y coordinador; registra el resultado de una alerta y cambia umbrales solo el coordinador; cargan el archivo del proveedor coordinador y finanzas; soporte solo consulta. Sin permiso, el botón queda deshabilitado con su explicación. | En una demo es más claro ver la acción deshabilitada con su motivo que esconder la pantalla. La API valida los permisos y responde 403. |
| 55 | `X-Demo-User` lleva el nombre visible codificado (`encodeURIComponent`). Los nombres son inventados (Laura Mendoza, Carlos Rivas, Marta Salcedo y Diego Paternina). | Las cabeceras HTTP no admiten tildes, y la bitácora debe decir "Laura Mendoza aprobó…", no un identificador. |
| 56 | El simulador tiene un botón "Siguiente paso del guion" por caso, además del campo de texto, la foto y las respuestas rápidas. | La demo dura 3 minutos: no hay tiempo de teclear y así no hay errores de digitación en vivo. |
| 57 | Los casos son chips por vehículo (VEH901, VEH015, VEH199, VEH902 y Sin registro) y el elegido se recuerda al ir y volver de la consola. La hora simulada se bloquea tras el primer mensaje. | El backend fija la hora del caso con el primer mensaje e ignora las siguientes. |
| 58 | En la consola, Aprobar, Ajustar y Rechazar están en una cabecera fija, y los motivos se piden en un cuadro con sugerencias de un clic. | A 1366×768 el detalle no cabe entero: las acciones deben quedar siempre a la vista. |
| 59 | El panel de habilitación es una franja bajo la cabecera, con botón de copiar por campo, "Copiar todo" y la referencia sugerida. | HU-15: valores precargados listos para el portal del proveedor. |
| 60 | La cola muestra todas las solicitudes del día: primero las abiertas, por tiempo de espera, y luego las cerradas, atenuadas. La espera y el SLA corren cada segundo en el navegador; la cola y el detalle se refrescan cada 3 s y el chat cada 1,2 s (polling, sin SSE). | La solicitud recién autorizada no debe desaparecer durante la demo. El polling es lo más simple y alcanza. |
| 61 | La bitácora traduce `before` y `after` a líneas en español y omite las claves que no conoce. | El JSON crudo no se puede leer proyectado. |
| 62 | `/alertas` tiene cuatro pestañas (Tanqueos con alerta, Vehículos, Conciliación y Reglas y umbrales). "Tanqueos con alerta" incluye las desviaciones de la conciliación. | Las cuatro son del coordinador y en el guion se recorren seguidas. |
| 63 | Al elegir el resultado de una alerta se precarga un comentario editable, y la acción que sigue sale de la tabla de la sección 6 del informe. | Para no teclear en la demo y mostrar qué pasa con una desviación confirmada. |
| 64 | El motivo es obligatorio en la interfaz al cambiar un umbral, aunque la API lo acepta vacío. | Un cambio de umbral sin motivo no sirve en la bitácora. |
| 65 | El libro único muestra los 8 movimientos más recientes, con "Ver todos" y filtro por proveedor. | 102 filas no caben en una pantalla proyectada. |
| 66 | Tablero: 9 tarjetas en 3 columnas; cada una dice si el valor es "Calculado con la demo" o "Valor ilustrativo". | Un valor de ejemplo no se puede hacer pasar por uno medido. |
| 67 | "Con los valores de hoy aplicaría" se calcula en el frontend con los seis criterios de Ampliar; Detener si hay vehículos sin combustible o la adopción baja de 50 %; lo demás es Ajustar. El criterio "tiempo peor que la línea base tras 4 semanas" no se evalúa. | En el prototipo no hay 4 semanas de historia. Tras el guion sale "Ajustar" porque no todas las solicitudes se aprueban en un clic; recién reiniciada la demo sale "Ampliar". |
| 68 | Las desviaciones abiertas del tablero (por prioridad, regla y antigüedad) se calculan en el frontend con `GET /alerts?status=open`. | Evita otra ruta en la API. |

## Verificación y entrega

| # | Decisión | Motivo |
|---|---|---|
| 69 | El guion de la demo se recorre con Playwright en modo headless (`e2e/scripts/demo-flow.mjs`) contra el stack real, a 1366×768 y a 1920×1080, y falla si hay errores de JavaScript, desborde horizontal, un pie de página distinto o una cifra que no coincide. | Las capturas de `docs/screenshots/` salen de ese recorrido, así que siempre corresponden al código. |
| 70 | Chromium se instala dentro de `e2e/node_modules`, no en el perfil del usuario. | Nada queda instalado de forma global en el equipo. |
| 71 | El guion de capturas añade casos que el prompt no pide: VEH902 (no necesita tanquear), número no registrado, solo lectura por rol, validaciones de motivo y tope, segunda carga del CSV, cambio de umbral y la cola con los tres semáforos. | Son los escenarios de las historias que más se preguntan en una sustentación. |
| 72 | Puertos publicados: 8080 (interfaz) y 8000 (API), configurables con `FRONTEND_PORT` y `BACKEND_PORT`. El proyecto de Compose se llama `esivans-combustible`. | Son los del prompt. El nombre fijo evita mezclarse con otros proyectos de Docker del equipo. |
| 73 | La carpeta `referencias/` (los 8 entregables de la prueba, su texto extraído y las notas de trabajo) está en `.gitignore`, como pide el prompt original, y ningún archivo ni fila de ella está copiado en el código. | Confidencialidad: los datos del caso son de uso exclusivo del proceso de selección. La semilla está escrita a mano con las cifras que citan los documentos. |
| 74 | Repositorio git local, sin remoto y sin `push`. | Lo pide el prompt. |
| 75 | Los totales de 90 días de la ficha del VEH015 y del VEH129 son la suma de sus tanqueos de la semilla ($4.984.000 y $4.128.960), y la proporción de tanqueos con alerta del VEH129 es 26 %. | En la misma pantalla salían dos cifras casi iguales (26 % y 27 %; $4.129.120 y $4.128.960). Las cifras de los documentos no cambian: 102 tanqueos por $4,1 M, 20,3 km/gal-eq y 8 puntos. |
| 76 | La razón "No necesita tanquear según el cálculo" dice "el conductor pidió que lo revise el técnico" solo cuando el conductor lo pidió; si acepta, o mientras no ha respondido, termina en "a cargar da 0 o menos." | La razón se guarda al evaluar, antes de la respuesta del conductor, y en una solicitud cerrada sin tanqueo contradecía el aviso "el conductor lo aceptó". |
| 77 | Un conductor registrado sin asignación vigente llega al técnico con la razón "Conductor sin vehículo asignado", no con "Número no registrado". | Son dos casos distintos: en uno hay que identificar el vehículo y en el otro al conductor. Ningún caso de la demo lo usa. |
| 78 | Si falla el procesamiento del primer mensaje de un número, el aviso de privacidad se envía junto con el mensaje de error. | El aviso se deshacía con la transacción fallida y, como el mensaje de error ya contaba como primer contacto, no volvía a salir. |
| 79 | Las pruebas se revisaron por mutación: 127 defectos sembrados de uno en uno en copias del código (108 en el backend y 19 en la interfaz); los que ninguna prueba detectó quedaron cubiertos con pruebas nuevas (`backend/tests/test_review_findings.py`, `backend/tests/test_concurrency.py` y `e2e/tests/hard-to-reach-states.spec.mjs`). | Una prueba que no puede fallar no garantiza nada. Las mutaciones se aplican sobre copias temporales, nunca sobre el repositorio. |

## Lo que no cubre el prototipo

Es un prototipo, no el MVP. De las historias que cubre, esto queda parcial o por fuera:

| Historia | Qué falta | Por qué |
|---|---|---|
| HU-01, escenario 4 | El asistente no pide la ubicación. | R10 necesita la estación real y solo se conoce al conciliar. |
| HU-03, escenario 3 | La foto ilegible está implementada (pide el km escrito), pero no hay una foto de ejemplo ilegible entre los casos. | Los cuatro casos de la demo tienen lectura clara. |
| HU-07, escenarios 1, 2 y 4 | No hay pantalla para cargar la ficha técnica; viene en la semilla. El tope sin capacidad registrada (escenario 3) está en el motor, pero ningún vehículo de la semilla lo usa. | El prompt deja HU-07 como "ficha técnica y tope en la semilla". |
| HU-09, escenario 5 | No hay modo sombra para las reglas. | No se ve en una demo de 3 minutos. |
| HU-12, escenarios 3 y 4 | No hay "dato no disponible" con su antigüedad ni alerta a soporte por hora pico. | Dependen de HU-21, que está fuera del prototipo. |
| HU-15, escenario 3 | La autorización guarda su vencimiento, pero no pasa sola a "vencida sin uso". | No hay proceso programado (sin worker). |
| HU-16, escenarios 1, 2 y 5 | Cada transacción se cruza con su autorización y se marca la diferencia de valor o de producto, pero no hay estados usada, parcial o no usada, ni cierre diario, y la diferencia de km entre la estación y la foto no se evalúa. Desde la interfaz solo se carga Terpel (la API también acepta `gopass`). | El prompt deja HU-16 como "conciliación simplificada". |
| HU-18, escenario 1 | La lista de vehículos existe con razón, puntaje y prioridad, pero no se genera por semana. | Viene calculada en la semilla. |
| HU-22, escenario 1 | Ingreso simulado con el selector de rol. | En producción es SSO (OIDC) con MFA. |
| Fuera del prototipo | HU-05, HU-06, HU-08, HU-11 (el cambio de umbral con versión sí está), HU-14, HU-20, HU-21, HU-23 (el aviso de privacidad sí sale en el chat) y HU-24. | Alcance definido en el prompt. |
