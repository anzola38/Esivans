# Plan del prototipo

Prototipo visual para una demo de 3 minutos del flujo principal: el conductor pide combustible por WhatsApp, el asistente arma la solicitud, el motor de reglas calcula el semáforo y el valor sugerido, el técnico decide en la consola y todo queda en la bitácora. No es el MVP: lo que se muestra funciona, y lo que no hace falta para la demo queda por fuera (ver `DECISIONES.md`).

Cada hito deja la aplicación corriendo con `docker compose up --build` y termina en un commit.

| Hito | Qué entrega | Estado |
|---|---|---|
| H1 | Esqueleto, `docker-compose.yml`, `/api/health` y el shell de Angular con el tema visual | Listo |
| H2 | Modelo de datos, migración de Alembic, semilla, motor de reglas (R01 a R14 y V01 a V08), valor recomendado y pruebas | Listo |
| H3 | Webhook firmado, orquestador de la conversación, adaptador de IA (mock) y mensajes salientes | Listo |
| H4 | Simulador y consola con el flujo completo del caso verde, del VEH015 y del VEH199 | Listo |
| H5 | Conciliación (VEH023), alertas y reglas por vehículo (VEH129 y VEH215) | Listo |
| H6 | Tablero del piloto con los 9 indicadores | Listo |
| H7 | Prueba desde cero, pulido visual, capturas revisadas, README y decisiones | Listo |

Si el tiempo no alcanzaba se recortaba desde el final: el flujo principal de H4 era lo que no podía faltar. No hizo falta recortar hitos; lo que quedó parcial dentro de las historias está en "Lo que no cubre el prototipo" de `DECISIONES.md`.

## Cómo se verifica

- **Desde cero:** `docker compose down -v && docker compose up -d --build`; los tres servicios quedan `healthy`.
- **Pruebas del backend** dentro del contenedor: `docker compose exec backend pytest` (27 pruebas: R02 del VEH015, VEH199 con 7 puntos y rojo, semáforo, fórmula con redondeo, tope y valor de 0 o menos, firma del webhook y el flujo del caso verde por la API).
- **Guion de la demo** con Playwright en modo headless: `cd e2e && npm run demo`. Recorre los 6 pasos y los casos de borde a 1366×768 y a 1920×1080, comprueba las cifras de los documentos y guarda las capturas en `docs/screenshots/`.
- **Pruebas del shell:** `cd e2e && npm test`.
- **Capturas:** revisadas en los dos tamaños (cortes, solapes, desbordes, formato es-CO, semáforo con texto y pie de página).
