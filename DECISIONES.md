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
| 12 | La vigencia de la autorización (2 horas) se guarda en hora real (`expires_at`), y al conductor se le muestra en la hora del caso (`expires_at_case_time`). | Cada pantalla es coherente con su reloj: la consola con el real y el simulador con el del caso. |
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
| 40 | En los textos del asistente y de las reglas la hora va en formato de 24 horas ("23:14"). | Es como la escribe el análisis en las razones de R09. |

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
