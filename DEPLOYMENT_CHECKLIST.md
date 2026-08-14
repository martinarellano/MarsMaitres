# MarsMaitre — preparación de despliegue público

## Estado actual

- Backend empaquetado con Docker.
- `render.yaml` preparado para un servicio web HTTPS.
- Health check: `/api/health`.
- `BILLING_MODE=cash` para evitar Mercado Pago.
- OAuth individual de Google Calendar preparado, pero no activo hasta registrar el dominio HTTPS.
- Los secretos se declaran como variables privadas; no se guardan en el repositorio.

## Variables obligatorias antes de producción

- `MARSMAITRE_PUBLIC_URL`: URL HTTPS definitiva.
- `GOOGLE_OAUTH_CLIENT_ID` y `GOOGLE_OAUTH_CLIENT_SECRET`.
- `GOOGLE_OAUTH_REDIRECT_URI`: debe coincidir exactamente con la URL pública más `/oauth/google/callback`.
- `TOKEN_ENCRYPTION_KEY`: generar con Fernet y guardar solo en el proveedor.
- `MARSMAITRE_ADMIN_EMAIL` y `MARSMAITRE_ADMIN_PASSWORD` con una contraseña nueva, no la temporal de desarrollo.
- `ALLOWED_ORIGIN` limitado al dominio HTTPS del panel.

## Pasos de publicación

1. Subir `work/` a un repositorio privado.
2. Crear el servicio web usando `render.yaml` o el Dockerfile.
3. Configurar las variables privadas.
4. Verificar `/api/health` por HTTPS.
5. Registrar el redirect URI en Google Cloud.
6. Probar login ADMIN y creación de un dueño.
7. Cambiar la contraseña temporal con `/api/account/change-password`.
8. Probar OAuth con una cuenta de restaurante de prueba.
9. Crear y confirmar una reservación; comprobar que se crea un evento real en el calendario autorizado.
10. Cancelar la reservación y comprobar que el evento se elimina de Google Calendar.
11. Confirmar que la base usa el disco persistente (`MARSMAITRE_DB_PATH=/data/marsmaitre.db`) y configurar respaldos periódicos.
12. Cambiar la contraseña temporal y verificar cierre de sesión y cambio de contraseña.

No se debe anunciar el servicio como producción hasta completar estos pasos.
