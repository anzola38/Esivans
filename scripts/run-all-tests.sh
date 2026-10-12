#!/usr/bin/env bash
# Runs every automated test of the prototype: the backend functional suite (pytest, inside the
# backend container) and the interface E2E suite (Playwright, both viewport sizes).
#
#   scripts/run-all-tests.sh            start the stack if needed and run both suites
#   scripts/run-all-tests.sh --build    rebuild the images first (use it after changing code)
#
# Exit code: 0 only when both suites pass. Both suites always run, even if the first one fails.
# The E2E suite resets the demo before each test and once more at the end.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

BUILD=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    -h|--help) sed -n '2,9p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Opción no reconocida: $arg" >&2; exit 2 ;;
  esac
done

for tool in docker node npm; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Falta '$tool' en el PATH." >&2; exit 2; }
done

section() { printf '\n==== %s ====\n' "$1"; }

healthy_services() {
  docker compose ps --format '{{.Service}} {{.Health}}' 2>/dev/null | grep -c ' healthy$'
}

section "Stack"
if [ "$BUILD" -eq 1 ]; then
  docker compose up -d --build --wait || { echo "No se pudo construir o levantar el stack." >&2; exit 2; }
elif [ "$(healthy_services)" -ne 3 ]; then
  docker compose up -d --wait || { echo "No se pudo levantar el stack." >&2; exit 2; }
fi
if [ "$(healthy_services)" -ne 3 ]; then
  echo "Los tres servicios (db, backend, frontend) deben estar sanos." >&2
  docker compose ps >&2
  exit 2
fi
docker compose ps --format '{{.Service}}: {{.Health}}'

section "Pruebas funcionales del backend (pytest)"
backend_start=$SECONDS
docker compose exec -T backend pytest -p no:cacheprovider
backend_status=$?
backend_seconds=$((SECONDS - backend_start))

section "Pruebas E2E de la interfaz (Playwright)"
e2e_start=$SECONDS
e2e_status=0
if [ ! -d "$ROOT/e2e/node_modules/@playwright/test" ]; then
  (cd "$ROOT/e2e" && npm run setup) || e2e_status=$?
fi
if [ "$e2e_status" -eq 0 ]; then
  (cd "$ROOT/e2e" && npm test)
  e2e_status=$?
fi
e2e_seconds=$((SECONDS - e2e_start))

result() { if [ "$1" -eq 0 ]; then echo "pasaron"; else echo "FALLARON (código $1)"; fi; }

section "Resumen"
echo "Backend (pytest):  $(result "$backend_status") en ${backend_seconds} s"
echo "E2E (Playwright):  $(result "$e2e_status") en ${e2e_seconds} s"

if [ "$backend_status" -ne 0 ] || [ "$e2e_status" -ne 0 ]; then
  exit 1
fi
exit 0
