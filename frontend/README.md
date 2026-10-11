# Frontend del prototipo

Angular 22 (componentes standalone, signals, control de flujo nuevo y rutas lazy), sin librería de componentes.
Se compila dentro de Docker con Node 24 y lo sirve nginx, que hace proxy de `/api/` a `http://backend:8000`.

```bash
docker build -t esivans-frontend-check .
docker run -d --name esivans-frontend-check -p 18080:80 esivans-frontend-check
```

- Pantallas: `/simulador`, `/consola`, `/consola/:id`, `/alertas` y `/tablero`.
- `/guia-estilo` muestra todos los componentes compartidos (no está en el menú).
- `src/app/core`: rol y usuario de la demo, cliente de la API, interceptor, avisos y formato es-CO.
- `src/app/shared`: componentes y pipes compartidos (`imports: [SHARED]`).
- `src/styles`: variables de color, base, shell, componentes y utilidades.

El ingreso es simulado con el selector de rol; en producción sería con SSO (OIDC) y MFA.
