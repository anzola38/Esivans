import { Injectable, computed, signal } from '@angular/core';
import { Permission, Role, RoleOption } from './models';

const STORAGE_KEY = 'esivans.demo.role';

export const ROLE_OPTIONS: readonly RoleOption[] = [
  {
    role: 'technician',
    label: 'Técnico de Control y Monitoreo',
    shortLabel: 'Técnico',
    user: { id: 'tecnico.demo', name: 'Laura Mendoza', initials: 'LM' },
  },
  {
    role: 'coordinator',
    label: 'Coordinador',
    shortLabel: 'Coordinador',
    user: { id: 'coordinador.demo', name: 'Carlos Rivas', initials: 'CR' },
  },
  {
    role: 'finance',
    label: 'Finanzas',
    shortLabel: 'Finanzas',
    user: { id: 'finanzas.demo', name: 'Marta Salcedo', initials: 'MS' },
  },
  {
    role: 'support',
    label: 'Soporte',
    shortLabel: 'Soporte',
    user: { id: 'soporte.demo', name: 'Diego Paternina', initials: 'DP' },
  },
];

const PERMISSIONS: Record<Permission, readonly Role[]> = {
  'request.decide': ['technician'],
  'alert.review': ['coordinator'],
  'rules.edit': ['coordinator'],
  'provider.import': ['coordinator', 'finance'],
  'demo.reset': ['technician', 'coordinator', 'finance', 'support'],
};

/** Simulated sign-in: the selected role lives in a signal and in localStorage. */
@Injectable({ providedIn: 'root' })
export class RoleService {
  readonly options = ROLE_OPTIONS;

  private readonly _role = signal<Role>(this.readStoredRole());

  readonly role = this._role.asReadonly();
  readonly current = computed<RoleOption>(
    () => ROLE_OPTIONS.find((o) => o.role === this._role()) ?? ROLE_OPTIONS[0],
  );
  readonly user = computed(() => this.current().user);
  readonly label = computed(() => this.current().label);

  setRole(role: Role): void {
    if (!ROLE_OPTIONS.some((o) => o.role === role)) return;
    this._role.set(role);
    try {
      localStorage.setItem(STORAGE_KEY, role);
    } catch {
      /* storage unavailable: the role still lives in memory */
    }
  }

  /** Reactive when read inside a template, computed or effect. */
  can(permission: Permission): boolean {
    return PERMISSIONS[permission].includes(this._role());
  }

  /** Readable list of the roles allowed to do something, for disabled-action hints. */
  rolesFor(permission: Permission): string {
    return PERMISSIONS[permission]
      .map((r) => ROLE_OPTIONS.find((o) => o.role === r)?.shortLabel ?? r)
      .join(' o ');
  }

  private readStoredRole(): Role {
    try {
      const stored = localStorage.getItem(STORAGE_KEY) as Role | null;
      if (stored && ROLE_OPTIONS.some((o) => o.role === stored)) return stored;
    } catch {
      /* ignore */
    }
    return 'technician';
  }
}
