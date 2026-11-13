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
5. Abre `http://127.0.0.1:5000` en tu navegador.

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

Compose conserva los datos de PostgreSQL y las imágenes subidas en los volúmenes `postgres_data` y `uploads`. Configura y prueba copias de seguridad de esos volúmenes antes de abrir la beta. No elimines los volúmenes al actualizar o recrear el recurso.

El contenedor requiere `SECRET_KEY` y PostgreSQL al ejecutarse en producción; no arrancará con secretos por defecto ni con SQLite efímero. Mantiene un worker Gunicorn y cuatro threads, adecuado como punto de partida para una beta pequeña. El actual actualizador de noticias corre dentro del proceso web: no escales réplicas de `app` sin antes separar ese scheduler para evitar ejecuciones duplicadas.

Este despliegue crea una base nueva y **no importa automáticamente** usuarios, publicaciones ni imágenes de una instalación local. Antes de abrir la beta, decide si quieres iniciar con datos vacíos o preparar una migración de `yamitas.db` y `static/uploads`.

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
