# Plan del prototipo

Prototipo visual para una demo de 3 minutos del flujo principal: el conductor pide combustible por WhatsApp, el asistente arma la solicitud, el motor de reglas calcula el semáforo y el valor sugerido, el técnico decide en la consola y todo queda en la bitácora. No es el MVP: lo que se muestra funciona, y lo que no hace falta para la demo queda por fuera (ver `DECISIONES.md`).

Cada hito deja la aplicación corriendo con `docker compose up --build`.

| Hito | Qué entrega | Estado |
|---|---|---|
| H1 | Esqueleto, `docker-compose.yml`, `/api/health` y el shell de Angular con el tema visual | Backend listo |
| H2 | Modelo de datos, migración de Alembic, semilla, motor de reglas (R01 a R14 y V01 a V08), valor recomendado y pruebas | Listo |
| H3 | Webhook firmado, orquestador de la conversación, adaptador de IA (mock) y mensajes salientes | Listo |
| H4 | Simulador y consola con el flujo completo del caso verde, del VEH015 y del VEH199 | API lista; interfaz en curso |
| H5 | Conciliación (VEH023), alertas y reglas por vehículo (VEH129 y VEH215) | API lista; interfaz en curso |
| H6 | Tablero del piloto con los 9 indicadores | API lista; interfaz en curso |
| H7 | Pulido visual, capturas y README | Pendiente |

Si el tiempo no alcanza se recorta desde el final: el flujo principal de H4 es lo que no puede faltar.

## Cómo se verifica

- Pruebas del backend dentro del contenedor: `docker compose exec backend pytest`.
- Recorrido por la API con `curl`: caso verde (VEH901), VEH015 y VEH199 de punta a punta, importación del CSV dos veces, una alerta cerrada y `POST /api/dev/reset`.
- Interfaz: recorrido del guion de la demo y capturas en `docs/screenshots/` (H7).
