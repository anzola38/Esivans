import { HttpContextToken, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';
import { APP_CONFIG } from './config';
import { RoleService } from './role.service';
import { ToastService } from './toast.service';

/** Set to true on a request to handle its errors locally, without the global toast. */
export const SILENT_ERRORS = new HttpContextToken<boolean>(() => false);

/** Turns any backend error into a short Spanish message. */
export function describeHttpError(error: unknown): string {
  if (!(error instanceof HttpErrorResponse)) return 'Ocurrió un error inesperado.';
  if ([0, 502, 503, 504].includes(error.status)) {
    return 'No hay conexión con el servidor. Verifica que el backend esté arriba.';
  }
  const body = error.error;
  const detail = body && typeof body === 'object' ? (body.detail ?? body.message) : null;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail) && detail.length && typeof detail[0]?.msg === 'string') {
    return detail.map((d: { msg: string }) => d.msg).join('. ');
  }
  switch (error.status) {
    case 400:
    case 422:
      return 'Los datos enviados no son válidos.';
    case 401:
    case 403:
      return 'Tu rol no tiene permiso para esta acción.';
    case 404:
      return 'No se encontró lo que buscabas.';
    case 409:
      return 'La acción choca con el estado actual. Actualiza e intenta de nuevo.';
    default:
      return 'El servidor no pudo completar la acción.';
  }
}

/** Adds the simulated identity headers to /api calls and reports errors with a toast. */
export const apiInterceptor: HttpInterceptorFn = (req, next) => {
  const roles = inject(RoleService);
  const toasts = inject(ToastService);

  const isApi = req.url.startsWith(APP_CONFIG.apiBaseUrl);
  const request = isApi
    ? req.clone({
        setHeaders: {
          'X-Demo-Role': roles.role(),
          // Encoded display name (HTTP headers are ASCII only); the backend decodes it for the audit log.
          'X-Demo-User': encodeURIComponent(roles.user().name),
        },
      })
    : req;

  return next(request).pipe(
    catchError((error: unknown) => {
      if (isApi && !req.context.get(SILENT_ERRORS)) {
        toasts.error(describeHttpError(error));
      }
      return throwError(() => error);
    }),
  );
};
