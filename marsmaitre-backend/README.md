# MarsMaitre backend — integración inicial

## Desarrollo local

```bash
python3 server.py
```

Abre `http://127.0.0.1:8787` para servir el panel web. La base local de desarrollo es `../marsmaitre.db`.

## API inicial

- `GET /api/health`
- `POST /api/login` → devuelve token de sesión de 12 horas.
- `GET /api/me` → requiere `Authorization: Bearer <token>`.
- `POST /api/logout`.
- `GET /api/dashboard` → solo ADMIN.
- `GET /api/restaurants` → solo ADMIN.
- `GET /api/subscriptions` → solo ADMIN.
- `GET /api/calls` → solo ADMIN.
- `GET /api/reports` → solo ADMIN.
- `POST /api/restaurants` → requiere token ADMIN.
- `GET /api/my/dashboard` → panel aislado para dueño/empleado, limitado por membresía; devuelve todos los restaurantes/sucursales permitidos.
- Las rutas `/api/my/*` aceptan `?restaurant_id=...` (o `X-Restaurant-Id`) y verifican la membresía antes de leer o modificar datos, para no mezclar sucursales.
- `GET /api/my/restaurant` y `GET /api/my/menu` → configuración y menú del restaurante asignado.
- `GET /api/my/feedback` → llamadas, transcripciones y retroalimentación del restaurante autorizado.
- `POST /api/voice/events` → webhook genérico para recibir llamadas completadas del proveedor de voz; valida `X-Voice-Signature` con `VOICE_WEBHOOK_SECRET` en producción y evita duplicados.
- `GET /api/my/agent` y `POST /api/my/agent/test` → configuración compilada y simulación de respuestas del agente.
- `GET /api/my/reservations` y `POST /api/my/reservations` → reservaciones aisladas por restaurante, pendientes de sincronizar con Calendar.
- `GET /api/my/calendar` y `POST /api/my/calendar/prepare` → estado y preparación de autorización individual; no marca conexión real sin OAuth.
- `GET /api/my/calendar/oauth/start` y `/oauth/google/callback` → flujo OAuth individual; requiere Client ID/Secret, redirect HTTPS y clave de cifrado configurados en el servidor.
- `POST /api/my/reservations/confirm` y `/cancel` → confirma/cancela y crea o elimina el evento real de Google Calendar cuando la conexión está autorizada; si no está conectada queda `pending_calendar`.
- `POST /api/my/settings`, `POST /api/my/menu` y `POST /api/my/menu/delete` → edición protegida por rol OWNER.
- `GET /api/restaurants/{id}/access` → usuarios de una cuenta, solo ADMIN.
- `POST /api/account/change-password` → cambia contraseña con validación PBKDF2; mínimo 12 caracteres.
- La configuración del restaurante guarda operador móvil, proveedor de voz, número de desvío y estado de telefonía; la línea Telcel no se conecta directamente al agente: requiere un número VoIP/proveedor externo y desvío de llamadas.
- `POST /api/invitations` → crea acceso de dueño/empleado y aplica límite del plan.
- `POST /api/access/revoke` → revoca acceso de un restaurante.
- `POST /api/billing/activate-cash` → activa manualmente una cuenta después de confirmar efectivo; requiere token ADMIN.
- `POST /api/billing/create-plan` → prepara un plan recurrente de Mercado Pago; requiere token ADMIN, `MARSMAITRE_PUBLIC_URL`, `MERCADOPAGO_ACCESS_TOKEN` y `BILLING_MODE=mercadopago`.
- `POST /api/mercadopago/webhook` → recepción inicial; el servidor debe consultar y validar el estado antes de activar acceso.

## Preparación de despliegue

Construir desde la carpeta `work` con `docker build -f marsmaitre-backend/Dockerfile .` y ejecutar con HTTPS delante del contenedor. En hosting, montar un disco persistente y usar `MARSMAITRE_DB_PATH=/data/marsmaitre.db`. `backup_db.py` crea respaldos consistentes en `/data/backups`; debe programarse además una copia fuera del proveedor. Configurar las variables de `.env.example` en el proveedor; nunca subir el Access Token al repositorio.

## Cuenta de demostración local

- Correo: `maartiinaaree.96@gmail.com`
- Contraseña temporal de desarrollo: `MarsMaitreDemo2026!`

Cámbiala antes de cualquier uso real.

Este backend solo es una base de desarrollo. Antes de usarlo con clientes requiere HTTPS, autenticación real, hash de contraseñas, sesiones, permisos por `account_id`/`restaurant_id`, secretos en variables de entorno, auditoría, límites de uso y pasarela de pago.
