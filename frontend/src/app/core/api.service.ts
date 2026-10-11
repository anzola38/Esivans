import { HttpClient, HttpContext, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { SILENT_ERRORS } from './api.interceptor';
import { APP_CONFIG } from './config';

export type QueryParams = Record<string, string | number | boolean | null | undefined>;

export interface ApiOptions {
  params?: QueryParams;
  /** Skip the global error toast (polling, optional data). The error still reaches the caller. */
  silent?: boolean;
}

/** Thin typed client over HttpClient. Paths are relative to /api, e.g. `api.get('/requests')`. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);

  get<T>(path: string, options: ApiOptions = {}): Observable<T> {
    return this.http.get<T>(this.url(path), this.build(options));
  }

  /** `body` may be a plain object (JSON) or a FormData (file upload). */
  post<T>(path: string, body: unknown = {}, options: ApiOptions = {}): Observable<T> {
    return this.http.post<T>(this.url(path), body, this.build(options));
  }

  put<T>(path: string, body: unknown = {}, options: ApiOptions = {}): Observable<T> {
    return this.http.put<T>(this.url(path), body, this.build(options));
  }

  patch<T>(path: string, body: unknown = {}, options: ApiOptions = {}): Observable<T> {
    return this.http.patch<T>(this.url(path), body, this.build(options));
  }

  delete<T>(path: string, options: ApiOptions = {}): Observable<T> {
    return this.http.delete<T>(this.url(path), this.build(options));
  }

  /** URL under /api, also useful for `<img [src]>` of photos served by the backend. */
  url(path: string): string {
    const base = APP_CONFIG.apiBaseUrl;
    if (/^https?:\/\//.test(path) || path === base || path.startsWith(base + '/')) return path;
    return base + (path.startsWith('/') ? '' : '/') + path;
  }

  private build(options: ApiOptions): { params: HttpParams; context: HttpContext } {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(options.params ?? {})) {
      if (value !== null && value !== undefined && value !== '') {
        params = params.set(key, String(value));
      }
    }
    return {
      params,
      context: new HttpContext().set(SILENT_ERRORS, options.silent ?? false),
    };
  }
}
