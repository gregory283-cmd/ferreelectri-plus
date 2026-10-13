# Configurar Google OAuth (resumen rápido)

1. Crear OAuth Client en Google Cloud Console:
   - APIs & Services → Credentials → Create Credentials → OAuth client ID
   - Application type: Web application
   - Authorized redirect URIs:
     - http://localhost:8000/oauth/complete/google-oauth2/
     - http://127.0.0.1:8000/oauth/complete/google-oauth2/
     - (opcional para allauth) http://localhost:8000/accounts/google/login/callback/

2. Copiar `Client ID` y `Client secret` en el archivo local `.env` (o establecer variables de entorno):

```powershell
setx GOOGLE_CLIENT_ID "<your-client-id>.apps.googleusercontent.com"
setx GOOGLE_CLIENT_SECRET "<your-client-secret>"
```

3. Reiniciar el servidor Django y probar login desde la aplicación:

```bash
python manage.py runserver
```

4. Abrir el navegador en:

```text
http://localhost:8000/cliente/login/
```

   Haz clic en el botón "Continuar con Google" o utiliza Google One Tap. No copies una URL de autorización manualmente desde una herramienta como `check_google_oauth`, porque esa URL puede faltar el parámetro `state` y provocar `AuthMissingParameter`.

5. Notas importantes:
   - No subas `.env` al repositorio. El proyecto ya ignora `.env` en `.gitignore`.
   - Si recibes `Error 401: deleted_client`, recrea el OAuth client en Google Cloud y actualiza las credenciales.
   - Asegúrate de que las **Authorized redirect URIs** en Google Cloud coinciden exactamente con las rutas listadas arriba. Añade también estas variantes si tienes errores `redirect_uri_mismatch`:

      - http://localhost:8000/oauth/complete/google-oauth2
      - http://127.0.0.1:8000/oauth/complete/google-oauth2
      - http://localhost:8000/accounts/google/login/callback/
      - http://127.0.0.1:8000/accounts/google/login/callback/
   - Para probar rápidamente desde la línea de comandos, ejecuta:

```bash
python manage.py check_google_oauth
```

  Esto imprimirá una URL de autorización que puedes abrir en tu navegador; si Google muestra "deleted_client" significa que el `Client ID` registrado fue eliminado en la consola.
