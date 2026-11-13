# Yamitas

Aplicación Flask para la gestión de animales, ferias, publicaciones y noticias enfocada en camélidos (llamas, alpacas, vicuñas y guanacos).

## Estructura del proyecto

- `app.py`: aplicación Flask principal, rutas y modelos.
- `api/index.py`: entrada para despliegue en Vercel como función Python.
- `requirements.txt`: dependencias Python.
- `vercel.json`: configuración de despliegue para Vercel.
- `runtime.txt` / `.python-version`: versión de Python compatible.
- `templates/`: plantillas Jinja2.
- `static/`: recursos públicos.
- `consejos_data/`: contenido markdown de consejos.

## Requisitos

- Python 3.12.x
- pip

## Instalación local

1. Crea un entorno virtual:
   ```bash
   python -m venv .venv
   ```
2. Activa el entorno virtual:
   - Windows:
     ```powershell
     .\.venv\Scripts\Activate.ps1
     ```
   - Linux/macOS:
     ```bash
     source .venv/bin/activate
     ```
3. Instala dependencias:
   ```bash
   pip install -r requirements.txt
   ```
4. Ejecuta la aplicación:
   ```bash
   python app.py
   ```
5. Abre `http://127.0.0.1:5000` en tu navegador. El servidor de desarrollo también habilita los chats en tiempo real.

## Despliegue en Coolify

El despliegue de Coolify ejecuta el sitio Flask completo: las páginas web y el backend comparten una aplicación y una base de datos, por lo que las cuentas y publicaciones son visibles desde un mismo servidor.

### Preparación

1. En Coolify, crea un recurso desde este repositorio y selecciona el archivo `docker-compose.yml` como configuración de Compose.
2. Define estas variables en el recurso, sin guardarlas en Git:
   - `SECRET_KEY`: secreto aleatorio para las sesiones de Flask.
   - `POSTGRES_PASSWORD`: contraseña aleatoria formada solo por letras y números hexadecimales, porque se usa dentro de `DATABASE_URL`.
   - `POSTGRES_DB` y `POSTGRES_USER` son opcionales; por defecto ambos se configuran como `yamitas`.

   Puedes generar los dos secretos en una terminal que tenga OpenSSL con `openssl rand -hex 32`. Usa un valor distinto para cada variable.
3. Configura el dominio HTTPS de Coolify para el servicio `app`, puerto `8000`, y despliega. No publiques el servicio `db`: la aplicación se conecta a PostgreSQL por la red privada de Compose.
4. Comprueba que `https://tu-dominio/healthz` responda `{"status":"ok"}`. El endpoint también verifica la conexión a la base de datos.

### Acceso temporal sin dominio propio

El servicio `tunnel` de Compose abre un Cloudflare Quick Tunnel hacia `app:8000`. Después del despliegue, consulta los logs del servicio `tunnel` en Coolify y busca la URL `https://...trycloudflare.com`. La URL es aleatoria y puede cambiar si el túnel se reinicia. No requiere abrir puertos en el router ni configurar DNS.

Esta URL permite que cualquiera que la conozca acceda a la aplicación desde Internet; no la compartas si no quieres hacerla pública. Quick Tunnels son para pruebas y no ofrecen un nombre estable. Para producción, configura un dominio propio y un túnel con nombre, o elimina el servicio `tunnel` de Compose si no necesitas acceso público.

Compose conserva los datos de PostgreSQL y las imágenes subidas en los volúmenes `postgres_data` y `uploads`. Configura y prueba copias de seguridad de esos volúmenes antes de abrir la beta. No elimines los volúmenes al actualizar o recrear el recurso.

El contenedor requiere `SECRET_KEY` y PostgreSQL al ejecutarse en producción; no arrancará con secretos por defecto ni con SQLite efímero. Flask-SocketIO corre en modo threading con un worker Gunicorn y 100 threads. No aumentes los workers ni escales réplicas de `app` sin configurar antes una cola de mensajes y sesiones persistentes para Socket.IO. El actual actualizador de noticias también corre dentro del proceso web: no escales réplicas sin separar ese scheduler para evitar ejecuciones duplicadas.

Este despliegue crea una base nueva y **no importa automáticamente** usuarios, publicaciones ni imágenes de una instalación local. Antes de abrir la beta, decide si quieres iniciar con datos vacíos o preparar una migración de `yamitas.db` y `static/uploads`.

## Panel de administración

Las cuentas nuevas no pueden asignarse permiqsos administrativos desde el registro. Primero registra una cuenta propia y, desde el servidor que usa la base de datos de producción, promuévela manualmente:

```bash
flask --app app promover-admin tu-correo@dominio.com
```

En Coolify, ejecuta el comando desde la consola del servicio `app`. Con Docker Compose local, ejecuta `docker compose exec app flask --app app promover-admin tu-correo@dominio.com`. El email debe pertenecer a una cuenta ya registrada. No concedas este rol a cuentas ajenas.

Luego inicia sesión y abre `/admin`. Allí puedes buscar usuarios, consultar sus datos básicos, suspender/reactivar cuentas y eliminarlas; en `/admin/contenido` puedes moderar animales, publicaciones y ferias/eventos. Las suspensiones impiden iniciar sesión y cierran una sesión existente en su siguiente solicitud. Eliminar una cuenta es permanente y elimina también sus animales, publicaciones y fuentes de noticias; las ferias/eventos no pertenecen a una cuenta. Haz una copia de seguridad antes de borrar datos.

Configura un `SECRET_KEY` secreto y estable en el servidor. Si no está definido, la aplicación genera uno al iniciar y las sesiones se invalidan cuando se reinicia.

Al iniciar la aplicación se agregan automáticamente a la tabla de usuarios los campos de rol y estado necesarios, conservando las cuentas existentes como usuarios activos sin privilegios administrativos.

## Consultas sobre animales en venta

Un comprador con sesión iniciada puede enviar una consulta desde el detalle de una publicación. El dueño responde desde `/mensajes`; la conversación y sus mensajes quedan guardados en la base de datos y se muestran en tiempo real cuando ambos tienen abierta esa conversación. Si Socket.IO no logra conectarse, el formulario sigue funcionando con recarga normal. No se envían notificaciones cuando el usuario no tiene el chat abierto.

Desde el detalle de una publicación, el enlace al perfil del publicador abre su perfil público con nombre y ubicación, si la tiene configurada.

## Despliegue en Vercel

Este proyecto está preparado para desplegar la aplicación Flask completa en Vercel usando una función Python.

### Pasos

1. Asegúrate de tener `requirements.txt` actualizado.
2. Sube el repositorio a GitHub.
3. Crea un nuevo proyecto en Vercel y conéctalo al repositorio.
4. Vercel detectará `vercel.json` y desplegará `api/index.py` como función Python.

### Configuración incluida

- `vercel.json` apunta al handler en `api/index.py`.
- `runtime.txt` y `.python-version` definen Python 3.12.4.
- `package.json` ya no contiene un script `build` para evitar que Vercel intente ejecutar un build de Node.

### Notas de despliegue

- En Vercel, el proyecto usa `/tmp` para almacenar SQLite y cargas temporales.
- El scheduler de noticias (`APScheduler`) se desactiva en despliegues serverless.
- Para usar Ollama local, configura `OLLAMA_COMMAND` y `OLLAMA_MODEL` si aplicas.

## Uso de Ollama (opcional)

Si quieres usar el asistente IA, instala Ollama localmente y define la variable de entorno `OLLAMA_COMMAND` con la ruta del ejecutable.

Ejemplo en PowerShell:
```powershell
$env:OLLAMA_COMMAND = 'C:\Program Files\Ollama\ollama.exe'
```

## Preparar repositorio Git

```bash
git init
git add .
git commit -m "Initial commit"
```

Luego conecta tu repo remoto y sube tus cambios:

```bash
git remote add origin https://github.com/<usuario>/<repositorio>.git
git branch -M main
git push -u origin main
```

## Advertencias

- El despliegue en Vercel es dinámico y mantiene Flask, SQLite y rutas HTML.
- Si buscas solo una versión estática, `build_static.py` puede generar archivos en `public/`, pero perderás login y funciones de backend.
