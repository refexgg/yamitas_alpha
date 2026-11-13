from flask import Flask, render_template, request, redirect, url_for, flash, abort, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import inspect, text, or_
from sqlalchemy.exc import SQLAlchemyError
import os
import click
import hmac
import secrets
from functools import wraps
import time
import base64
import io
import csv
import subprocess
from datetime import datetime
from PIL import Image
import requests
from bs4 import BeautifulSoup
import json
import feedparser
from urllib.parse import urljoin, urlparse
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import timedelta
import re
import markdown

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)


def is_vercel_deployment():
    return (
        os.environ.get('VERCEL', '').lower() in ('1', 'true', 'yes') or
        os.environ.get('VERCEL_ENV', '').lower() in ('production', 'preview', 'development') or
        bool(os.environ.get('VERCEL_URL'))
    )

VERCEL_DEPLOY = is_vercel_deployment()

database_url = os.environ.get('DATABASE_URL')
if not database_url:
    if VERCEL_DEPLOY:
        database_url = 'sqlite:////tmp/yamitas.db'
    else:
        default_db_path = os.path.join(app.root_path, 'yamitas.db')
        try:
            if os.access(app.root_path, os.W_OK):
                database_url = 'sqlite:///yamitas.db'
            else:
                raise PermissionError
        except Exception:
            database_url = 'sqlite:////tmp/yamitas.db'

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['REMEMBER_COOKIE_DURATION'] = int(os.environ.get('REMEMBER_COOKIE_DURATION', 86400 * 30))  # 30 días
app.config['REMEMBER_COOKIE_SECURE'] = os.environ.get('REMEMBER_COOKIE_SECURE', 'False').lower() in ('1', 'true', 'yes')
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
default_upload_folder = os.path.join(app.root_path, 'static', 'uploads')
if VERCEL_DEPLOY:
    default_upload_folder = '/tmp/uploads'

app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', default_upload_folder)
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('MAX_CONTENT_LENGTH', 16 * 1024 * 1024))  # 16 MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
except OSError:
    # Fallback to a writeable temp directory on serverless platforms
    fallback_upload_folder = os.path.join('/tmp', 'uploads')
    try:
        os.makedirs(fallback_upload_folder, exist_ok=True)
        app.config['UPLOAD_FOLDER'] = fallback_upload_folder
    except OSError:
        pass

@app.before_request
def serve_uploads():
    pass

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Necesitas iniciar sesión para acceder a esta página.'
login_manager.login_message_category = 'warning'


@app.context_processor
def inject_active_page():
    endpoint = request.endpoint or ''
    page_map = {
        'index': 'inicio',
        'ferias': 'ferias',
        'publicar': 'publicar',
        'perfil': 'perfil',
        'registro_animales': 'registro_animales',
        'admin': 'admin',
        'admin_content': 'admin',
    }
    return {
        'active_page': page_map.get(endpoint, ''),
        'admin_csrf_token': admin_csrf_token,
    }


def admin_csrf_token():
    token = session.get('_admin_csrf_token')
    if token is None:
        token = secrets.token_urlsafe(32)
        session['_admin_csrf_token'] = token
    return token


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


def validate_admin_csrf():
    submitted_token = request.form.get('csrf_token', '')
    stored_token = session.get('_admin_csrf_token', '')
    if not stored_token or not hmac.compare_digest(submitted_token, stored_token):
        abort(400, description='Token de seguridad inválido. Recarga la página e inténtalo nuevamente.')


@app.before_request
def end_suspended_user_session():
    if current_user.is_authenticated and not current_user.is_active:
        logout_user()
        flash('Tu cuenta está suspendida. Contacta al administrador.', 'danger')

# ==================== MODELOS ====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    tipo_usuario = db.Column(db.String(50), default='comprador')  # comprador, vendedor
    ubicacion = db.Column(db.String(255), nullable=True)  # lugar de producción
    fecha_registro = db.Column(db.DateTime, default=db.func.current_timestamp())
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())

class Producto(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    precio = db.Column(db.Float, nullable=False)
    tipo = db.Column(db.String(50), nullable=False)  # reproductor, ganador, animal, etc
    foto = db.Column(db.String(255), nullable=True) 
    edad = db.Column(db.String(50), nullable=False)
    peso = db.Column(db.String(50), nullable=False)
    tamano = db.Column(db.String(50), nullable=False)
    raza = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(100), nullable=False)
    numero_servicios = db.Column(db.Integer, nullable=True)
    numero_carabana = db.Column(db.String(100), nullable=True)
    senal = db.Column(db.String(100), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    usuario = db.relationship('User', backref=db.backref('productos', lazy=True))
    fecha_creacion = db.Column(db.DateTime, default=db.func.current_timestamp())

class Evento(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    fecha = db.Column(db.DateTime, nullable=False)
    ubicacion = db.Column(db.String(100))
    fecha_creacion = db.Column(db.DateTime, default=db.func.current_timestamp())

class Animal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    edad = db.Column(db.String(50), nullable=False)
    peso = db.Column(db.String(50), nullable=False)
    tamano = db.Column(db.String(50), nullable=False)
    raza = db.Column(db.String(100), nullable=False)
    genero = db.Column(db.String(50), nullable=True)
    color = db.Column(db.String(100), nullable=False)
    numero_servicios = db.Column(db.Integer, nullable=True)
    numero_carabana = db.Column(db.String(100), nullable=True)
    senal = db.Column(db.String(100), nullable=True)
    foto = db.Column(db.String(255), nullable=True)
    descripcion = db.Column(db.Text, nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    usuario = db.relationship('User', backref=db.backref('animales', lazy=True))
    fecha_creacion = db.Column(db.DateTime, default=db.func.current_timestamp())
    fecha_modificacion = db.Column(db.DateTime, default=db.func.current_timestamp(), onupdate=db.func.current_timestamp())


class NewsSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    url = db.Column(db.String(2048), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=db.func.current_timestamp())

    usuario = db.relationship('User', backref=db.backref('news_sources', lazy=True))


class GlobalNewsSource(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(2048), nullable=False)
    fecha_creacion = db.Column(db.DateTime, default=db.func.current_timestamp())


class NewsItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(2048), unique=True, nullable=False)
    title = db.Column(db.String(1024), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)
    fetched_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    source_id = db.Column(db.Integer, db.ForeignKey('news_source.id'), nullable=True)
    global_source_id = db.Column(db.Integer, db.ForeignKey('global_news_source.id'), nullable=True)

    source = db.relationship('NewsSource', backref=db.backref('items', lazy=True))
    global_source = db.relationship('GlobalNewsSource', backref=db.backref('items', lazy=True))

class Consejo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    contenido = db.Column(db.Text, nullable=False)
    categoria = db.Column(db.String(100), nullable=True)
    fecha_creacion = db.Column(db.DateTime, default=db.func.current_timestamp())

class SubConsejoMarkdown(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    consejo_id = db.Column(db.Integer, db.ForeignKey('consejo.id'), nullable=False)
    titulo = db.Column(db.String(200), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    imagen = db.Column(db.String(255), nullable=True)
    orden = db.Column(db.Integer, default=0)
    fecha_creacion = db.Column(db.DateTime, default=db.func.current_timestamp())
    
    consejo = db.relationship('Consejo', backref=db.backref('subconejos', lazy=True))

@app.route('/static/uploads/<path:filename>')
def serve_upload(filename):
    from flask import send_from_directory
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== RUTAS ====================
@app.route('/debug/static-check')
def debug_static_check():
    import os
    static_path = app.static_folder
    bootstrap_css = os.path.join(static_path, 'css', 'bootstrap.min.css')
    style_css = os.path.join(static_path, 'css', 'style.css')
    
    # Check if files exist and their sizes
    bootstrap_size = 0
    style_size = 0
    
    if os.path.exists(bootstrap_css):
        bootstrap_size = os.path.getsize(bootstrap_css)
    
    if os.path.exists(style_css):
        style_size = os.path.getsize(style_css)
    
    return {
        'app_root': app.root_path,
        'static_folder': static_path,
        'static_folder_exists': os.path.exists(static_path) if static_path else False,
        'bootstrap_exists': os.path.exists(bootstrap_css),
        'bootstrap_path': bootstrap_css,
        'bootstrap_size': bootstrap_size,
        'style_exists': os.path.exists(style_css),
        'style_path': style_css,
        'style_size': style_size,
        'css_files': os.listdir(os.path.join(static_path, 'css')) if os.path.exists(os.path.join(static_path, 'css')) else [],
        'vercel_env': bool(os.environ.get('VERCEL')),
        'working_dir': os.getcwd(),
    }

@app.route('/debug/test-css')
def debug_test_css():
    """Test serving CSS directly through Flask"""
    import os
    static_path = app.static_folder
    bootstrap_css = os.path.join(static_path, 'css', 'bootstrap.min.css')
    
    if os.path.exists(bootstrap_css):
        from flask import send_file
        return send_file(bootstrap_css, mimetype='text/css')
    
    return {'error': 'bootstrap.min.css not found'}, 404

# Catch-all route to serve static files explicitly in Vercel
@app.route('/static/<path:filepath>', methods=['GET'])
def serve_static(filepath):
    """Serve static files explicitly for Vercel compatibility"""
    import os
    from flask import send_file, abort
    
    static_path = app.static_folder
    full_path = os.path.join(static_path, filepath)
    
    # Security: prevent directory traversal
    if not os.path.abspath(full_path).startswith(os.path.abspath(static_path)):
        abort(404)
    
    # Check if file exists
    if not os.path.isfile(full_path):
        abort(404)
    
    # Determine MIME type
    import mimetypes
    mime_type, _ = mimetypes.guess_type(full_path)
    if not mime_type:
        if full_path.endswith('.css'):
            mime_type = 'text/css'
        elif full_path.endswith('.js'):
            mime_type = 'application/javascript'
        elif full_path.endswith('.json'):
            mime_type = 'application/json'
        elif full_path.endswith('.woff2'):
            mime_type = 'font/woff2'
        elif full_path.endswith('.woff'):
            mime_type = 'font/woff'
        elif full_path.endswith('.ttf'):
            mime_type = 'font/ttf'
        else:
            mime_type = 'application/octet-stream'
    
    response = send_file(full_path, mimetype=mime_type)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response

@app.route('/')
def index():
    news_items = []

    def fetch_title(url):
        title = None
        try:
            resp = requests.get(url, timeout=5, headers={'User-Agent': 'yamitas-bot/1.0'})
            if resp.ok:
                soup = BeautifulSoup(resp.text, 'html.parser')
                og = soup.find('meta', property='og:title')
                if og and og.get('content'):
                    title = og.get('content').strip()
                if not title:
                    t = soup.find('title')
                    if t and t.text:
                        title = t.text.strip()
                if not title:
                    h1 = soup.find('h1')
                    if h1 and h1.text:
                        title = h1.text.strip()
        except Exception:
            title = None
        return title or 'Sin título'

    # Show latest cached global news items only (most recent first, alternated by source when multiple URLs are configured)
    try:
        global_sources = GlobalNewsSource.query.order_by(GlobalNewsSource.id).all()
        current_global_ids = [g.id for g in global_sources]
        if current_global_ids:
            recent = NewsItem.query.filter(NewsItem.global_source_id.in_(current_global_ids))
        else:
            recent = NewsItem.query.filter(NewsItem.global_source_id.isnot(None))
        recent = recent.order_by(NewsItem.published_at.desc().nullslast(), NewsItem.fetched_at.desc()).limit(50).all()

        if not recent and current_global_ids:
            update_all_sources()
            recent = NewsItem.query.filter(NewsItem.global_source_id.in_(current_global_ids))
            recent = recent.order_by(NewsItem.published_at.desc().nullslast(), NewsItem.fetched_at.desc()).limit(50).all()

        if current_global_ids:
            # alternate across sources, showing up to 5 items
            grouped = {g.id: [] for g in global_sources}
            for it in recent:
                if it.global_source_id in grouped:
                    grouped[it.global_source_id].append(it)

            source_ids = list(grouped.keys())
            idx = 0
            while len(news_items) < 5 and any(grouped[s] for s in source_ids):
                source_id = source_ids[idx % len(source_ids)]
                if grouped[source_id]:
                    it = grouped[source_id].pop(0)
                    news_items.append({'id': it.id, 'url': it.url, 'title': it.title, 'is_global': True})
                idx += 1
        else:
            for it in recent[:5]:
                news_items.append({'id': it.id, 'url': it.url, 'title': it.title, 'is_global': True})

        if not news_items and current_global_ids:
            # fallback placeholder while the first news fetch completes
            news_items.append({
                'id': 'placeholder',
                'url': global_sources[0].url,
                'title': 'Cargando noticias de la fuente principal...',
                'is_global': True,
                'placeholder': True
            })
    except Exception:
        # fallback to showing configured sources if DB query fails
        try:
            global_sources = GlobalNewsSource.query.all()
            for s in global_sources:
                news_items.append({'id': f'g-{s.id}', 'url': s.url, 'title': fetch_title(s.url), 'is_global': True})
        except Exception:
            pass

    return render_template('index.html', news_items=news_items)

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        tipo = 'comprador'

        if not username or not email or not password:
            flash('Completa todos los campos para continuar.', 'warning')
            return render_template('registro.html', username=username, email=email)

        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres.', 'danger')
            return render_template('registro.html', username=username, email=email)

        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya está en uso.', 'danger')
            return render_template('registro.html', username=username, email=email)

        if User.query.filter_by(email=email).first():
            flash('El email ya está registrado.', 'danger')
            return render_template('registro.html', username=username, email=email)

        nuevo_usuario = User(
            username=username,
            email=email,
            password=generate_password_hash(password),
            tipo_usuario=tipo
        )
        db.session.add(nuevo_usuario)
        db.session.commit()

        flash('Registro exitoso. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('login'))
    
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        usuario = User.query.filter_by(username=username).first()

        if usuario and usuario.is_active and check_password_hash(usuario.password, password):
            login_user(usuario, remember=True)
            flash('Has iniciado sesión correctamente.', 'success')
            return redirect(url_for('index'))

        if usuario and not usuario.is_active:
            flash('Tu cuenta está suspendida. Contacta al administrador.', 'danger')
            return render_template('login.html', username=username)

        flash('Usuario o contraseña inválidos.', 'danger')
        return render_template('login.html', username=username)
    
    return render_template('login.html')

@app.route('/perfil')
@login_required
def perfil():
    return render_template('perfil.html')

@app.route('/editar-ubicacion', methods=['POST'])
@login_required
def editar_ubicacion():
    ubicacion = request.form.get('ubicacion', '').strip()
    
    if not ubicacion:
        flash('La ubicación no puede estar vacía.', 'warning')
        return redirect(url_for('perfil'))
    
    if len(ubicacion) > 255:
        flash('La ubicación no puede exceder 255 caracteres.', 'danger')
        return redirect(url_for('perfil'))
    
    current_user.ubicacion = ubicacion
    db.session.commit()
    flash('Ubicación actualizada correctamente.', 'success')
    return redirect(url_for('perfil'))


@app.route('/news-sources/add', methods=['POST'])
@login_required
def add_news_source():
    url = request.form.get('news_url', '').strip()
    if not url:
        flash('Ingresa la URL de la fuente.', 'warning')
        return redirect(url_for('index'))

    if not (url.startswith('http://') or url.startswith('https://')):
        flash('La URL debe comenzar con http:// o https://', 'danger')
        return redirect(url_for('index'))

    # Limitar cantidad de fuentes por usuario
    existing_count = NewsSource.query.filter_by(usuario_id=current_user.id).count()
    if existing_count >= 10:
        flash('Has alcanzado el límite de 10 fuentes.', 'warning')
        return redirect(url_for('index'))

    nuevo = NewsSource(usuario_id=current_user.id, url=url)
    db.session.add(nuevo)
    db.session.commit()
    flash('Fuente añadida correctamente.', 'success')
    return redirect(url_for('index'))


@app.route('/news-sources/remove', methods=['POST'])
@login_required
def remove_news_source():
    source_id = request.form.get('source_id')
    if not source_id:
        return redirect(url_for('index'))

    source = NewsSource.query.filter_by(id=source_id, usuario_id=current_user.id).first()
    if source:
        db.session.delete(source)
        db.session.commit()
        flash('Fuente eliminada.', 'info')

    return redirect(url_for('index'))


def find_feed_url(page_url):
    try:
        resp = requests.get(page_url, timeout=6, headers={'User-Agent': 'yamitas-bot/1.0'})
        if not resp.ok:
            return None
        soup = BeautifulSoup(resp.text, 'html.parser')
        link = soup.find('link', type='application/rss+xml') or soup.find('link', type='application/atom+xml')
        if link and link.get('href'):
            return urljoin(page_url, link.get('href'))
    except Exception:
        return None
    return None


def fetch_from_feed(feed_url, global_source=None, user_source=None):
    try:
        f = feedparser.parse(feed_url)
        entries = []
        for e in f.entries[:10]:
            link = e.get('link') or e.get('id')
            title = e.get('title', 'Sin título')
            summary = e.get('summary', '')
            published = None
            if hasattr(e, 'published_parsed') and e.published_parsed:
                published = datetime.fromtimestamp(time.mktime(e.published_parsed))
            entries.append({'link': link, 'title': title, 'summary': summary, 'published': published})
        return entries
    except Exception:
        return []


def fetch_article_title(article_url):
    try:
        r = requests.get(article_url, timeout=6, headers={'User-Agent': 'yamitas-bot/1.0'})
        if not r.ok:
            return None
        s = BeautifulSoup(r.text, 'html.parser')
        og = s.find('meta', property='og:title')
        if og and og.get('content'):
            return og.get('content').strip()
        t = s.find('title')
        if t and t.text:
            return t.text.strip()
        h1 = s.find('h1')
        if h1 and h1.text:
            return h1.text.strip()
    except Exception:
        return None
    return None


def fetch_from_html(page_url):
    # Simple heuristic: collect first distinct article links from same host
    try:
        r = requests.get(page_url, timeout=6, headers={'User-Agent': 'yamitas-bot/1.0'})
        if not r.ok:
            return []
        s = BeautifulSoup(r.text, 'html.parser')
        anchors = s.find_all('a', href=True)
        parsed = urlparse(page_url)
        collected = []
        seen = set()
        for a in anchors:
            href = a['href']
            href = urljoin(page_url, href)
            p = urlparse(href)
            if p.netloc != parsed.netloc:
                continue
            if href in seen:
                continue
            seen.add(href)
            # skip links to same page or index
            if href.rstrip('/').lower() == page_url.rstrip('/').lower():
                continue
            title = a.get_text(strip=True)
            if not title or len(title) < 15:
                # try getting article page title
                title = fetch_article_title(href) or title
            collected.append({'link': href, 'title': title or 'Sin título', 'summary': '', 'published': None})
            if len(collected) >= 10:
                break
        return collected
    except Exception:
        return []


def extract_article_text(article_url):
    try:
        r = requests.get(article_url, timeout=8, headers={'User-Agent': 'yamitas-bot/1.0'})
        if not r.ok:
            return ''
        s = BeautifulSoup(r.text, 'html.parser')
        paragraphs = [p.get_text(separator=' ', strip=True) for p in s.find_all('p') if p.get_text(strip=True)]
        return ' '.join(paragraphs)
    except Exception:
        return ''


def is_llama_related(text):
    if not text:
        return False
    text = text.lower()
    keywords = [
        r"\bllama\b",
        r"\ballamas\b",
        r"\bcam[eé]lidos?\b",
        r"\bcam[eé]lido\b",
        r"\balpacas?\b",
        r"\bvicu[nñ]a\b",
        r"\bguanacos?\b",
        r"\bfibra\b",
        r"\bcr[ií]a\b",
        r"\breba[nñ]o\b",
        r"\bficha\b",
        r"\bchaccu\b"
    ]
    return any(re.search(pattern, text) for pattern in keywords)


def update_source_articles_for_url(url, global_source=None, user_source=None):
    # Try feed first
    entries = []
    feed_url = find_feed_url(url)
    if feed_url:
        entries = fetch_from_feed(feed_url, global_source=global_source, user_source=user_source)
    if not entries:
        # try url as feed
        entries = fetch_from_feed(url, global_source=global_source, user_source=user_source)
    if not entries:
        entries = fetch_from_html(url)

    for e in entries:
        link = e.get('link')
        if not link:
            continue
        # ensure absolute
        link = urljoin(url, link)
        # check existing
        if NewsItem.query.filter_by(url=link).first():
            continue
        title = e.get('title') or fetch_article_title(link) or 'Sin título'
        summary = e.get('summary')
        combined_text = f"{title}\n{summary or ''}"

        if not is_llama_related(combined_text):
            # Try full article text if title/summary is not enough
            page_text = extract_article_text(link)
            if not is_llama_related(page_text):
                continue

        published = e.get('published')
        ni = NewsItem(url=link, title=title[:1024], summary=summary, published_at=published)
        if global_source:
            ni.global_source_id = global_source.id
        if user_source:
            ni.source_id = user_source.id
        db.session.add(ni)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def update_all_sources():
    with app.app_context():
        try:
            globals = GlobalNewsSource.query.all()
            for g in globals:
                update_source_articles_for_url(g.url, global_source=g)
        except Exception:
            pass

        # No longer using per-user news sources for the main panel
        # kept for compatibility, but these items are not shown in the main carousel.


# create and start scheduler only when running as a long-lived server
if not VERCEL_DEPLOY:
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=update_all_sources, trigger='interval', minutes=15, next_run_time=datetime.now())
    scheduler.start()

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('index'))


@app.cli.command('promover-admin')
@click.argument('email')
def promote_admin(email):
    """Concede acceso de administrador a una cuenta existente."""
    user = User.query.filter(db.func.lower(User.email) == email.strip().lower()).first()
    if user is None:
        raise click.ClickException('No existe una cuenta registrada con ese email.')
    if user.is_admin:
        click.echo(f'{user.email} ya tiene permisos de administrador.')
        return

    user.is_admin = True
    db.session.commit()
    click.echo(f'Permisos de administrador concedidos a {user.email}.')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def normalize_foto_path(foto_path):
    """Normaliza la ruta de la foto a usar siempre /"""
    if foto_path:
        return foto_path.replace('\\', '/')
    return foto_path


def ensure_producto_columns():
    inspector = inspect(db.engine)
    if 'producto' not in inspector.get_table_names():
        return

    existing = {col['name'] for col in inspector.get_columns('producto')}
    migrations = []

    if 'foto' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN foto VARCHAR(255)")
    if 'edad' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN edad VARCHAR(50) DEFAULT ''")
    if 'peso' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN peso VARCHAR(50) DEFAULT ''")
    if 'tamano' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN tamano VARCHAR(50) DEFAULT ''")
    if 'raza' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN raza VARCHAR(100) DEFAULT ''")
    if 'color' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN color VARCHAR(100) DEFAULT ''")
    if 'numero_servicios' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN numero_servicios INTEGER")
    if 'numero_carabana' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN numero_carabana VARCHAR(100)")
    if 'senal' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN senal VARCHAR(100)")
    if 'usuario_id' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN usuario_id INTEGER")
    if 'fecha_creacion' not in existing:
        migrations.append("ALTER TABLE producto ADD COLUMN fecha_creacion DATETIME")

    if migrations:
        with db.engine.connect() as conn:
            for statement in migrations:
                conn.execute(text(statement))
            conn.commit()


def ensure_user_columns():
    inspector = inspect(db.engine)
    if 'user' not in inspector.get_table_names():
        return

    existing = {column['name'] for column in inspector.get_columns('user')}
    migrations = []
    if 'is_admin' not in existing:
        migrations.append('ALTER TABLE "user" ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE')
    if 'is_active' not in existing:
        migrations.append('ALTER TABLE "user" ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE')

    if migrations:
        with db.engine.begin() as conn:
            for statement in migrations:
                conn.execute(text(statement))


@app.route('/admin')
@admin_required
def admin():
    search = request.args.get('q', '').strip()[:100]
    page = request.args.get('page', 1, type=int) or 1
    users_query = User.query
    if search:
        pattern = f'%{search}%'
        users_query = users_query.filter(or_(
            User.username.ilike(pattern),
            User.email.ilike(pattern)
        ))

    users = users_query.order_by(User.fecha_registro.desc(), User.id.desc()).paginate(
        page=max(page, 1),
        per_page=25,
        error_out=False
    )
    return render_template(
        'admin.html',
        users=users,
        search=search,
        user_count=User.query.count(),
        animal_count=Animal.query.count(),
        publication_count=Producto.query.count(),
        event_count=Evento.query.count()
    )


@app.route('/admin/usuarios/<int:user_id>/estado', methods=['POST'])
@admin_required
def admin_toggle_user(user_id):
    validate_admin_csrf()
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('No puedes cambiar el estado de tu propia cuenta.', 'warning')
    elif user.is_active and user.is_admin and User.query.filter_by(is_admin=True, is_active=True).count() <= 1:
        flash('No puedes suspender al último administrador activo.', 'warning')
    else:
        user.is_active = not user.is_active
        db.session.commit()
        state = 'reactivada' if user.is_active else 'suspendida'
        flash(f'La cuenta de {user.username} fue {state}.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/usuarios/<int:user_id>/eliminar', methods=['POST'])
@admin_required
def admin_delete_user(user_id):
    validate_admin_csrf()
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('No puedes eliminar tu propia cuenta desde el panel.', 'warning')
        return redirect(url_for('admin'))
    if user.is_admin and user.is_active and User.query.filter_by(is_admin=True, is_active=True).count() <= 1:
        flash('No puedes eliminar al último administrador activo.', 'warning')
        return redirect(url_for('admin'))

    username = user.username
    try:
        source_ids = [source.id for source in NewsSource.query.filter_by(usuario_id=user.id).all()]
        if source_ids:
            NewsItem.query.filter(NewsItem.source_id.in_(source_ids)).delete(synchronize_session=False)
        NewsSource.query.filter_by(usuario_id=user.id).delete(synchronize_session=False)
        Animal.query.filter_by(usuario_id=user.id).delete(synchronize_session=False)
        Producto.query.filter_by(usuario_id=user.id).delete(synchronize_session=False)
        db.session.delete(user)
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        app.logger.exception('Error al eliminar la cuenta %s desde el panel', user_id)
        flash('No se pudo eliminar la cuenta por un error de base de datos. Revisa los registros del servidor.', 'danger')
        return redirect(url_for('admin'))

    flash(f'La cuenta de {username} y sus datos asociados fueron eliminados.', 'success')
    return redirect(request.referrer or url_for('admin'))


@app.route('/admin/contenido')
@admin_required
def admin_content():
    return render_template(
        'admin_contenido.html',
        animals=Animal.query.order_by(Animal.fecha_creacion.desc()).limit(100).all(),
        publications=Producto.query.order_by(Producto.fecha_creacion.desc()).limit(100).all(),
        events=Evento.query.order_by(Evento.fecha.desc()).limit(100).all()
    )


@app.route('/admin/animales/<int:animal_id>/eliminar', methods=['POST'])
@admin_required
def admin_delete_animal(animal_id):
    validate_admin_csrf()
    animal = Animal.query.get_or_404(animal_id)
    name = animal.nombre
    db.session.delete(animal)
    db.session.commit()
    flash(f'El animal "{name}" fue eliminado.', 'success')
    return redirect(url_for('admin_content'))


@app.route('/admin/publicaciones/<int:publication_id>/eliminar', methods=['POST'])
@admin_required
def admin_delete_publication(publication_id):
    validate_admin_csrf()
    publication = Producto.query.get_or_404(publication_id)
    name = publication.nombre
    db.session.delete(publication)
    db.session.commit()
    flash(f'La publicación "{name}" fue eliminada.', 'success')
    return redirect(url_for('admin_content'))


@app.route('/admin/ferias/<int:event_id>/eliminar', methods=['POST'])
@admin_required
def admin_delete_event(event_id):
    validate_admin_csrf()
    event = Evento.query.get_or_404(event_id)
    name = event.nombre
    db.session.delete(event)
    db.session.commit()
    flash(f'La feria o evento "{name}" fue eliminado.', 'success')
    return redirect(url_for('admin_content'))


@app.route('/publicar', methods=['GET', 'POST'])
@login_required
def publicar():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio = request.form.get('precio', '').strip()
        edad = request.form.get('edad', '').strip()
        peso = request.form.get('peso', '').strip()
        tamano = request.form.get('tamano', '').strip()
        raza = request.form.get('raza', '').strip()
        color = request.form.get('color', '').strip()
        numero_servicios = request.form.get('numero_servicios', '').strip()
        numero_carabana = request.form.get('numero_carabana', '').strip()
        senal = request.form.get('senal', '').strip()
        tipo = 'reproductor'

        ensure_producto_columns()
        
        # Procesar imagen: puede venir como archivo o como base64
        foto_ruta = None
        foto_base64 = request.form.get('foto', '').strip()
        foto = request.files.get('foto')
        
        if foto_base64 and foto_base64.startswith('data:image'):
            # Procesar imagen base64 (recortada)
            try:
                # Extraer el base64 del data URL
                header, encoded = foto_base64.split(',', 1)
                image_data = base64.b64decode(encoded)
                image = Image.open(io.BytesIO(image_data))
                
                # Generar nombre de archivo
                filename = f"{current_user.id}_{int(time.time())}_cropped.jpg"
                destino = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # Guardar como JPEG optimizado
                image.convert('RGB').save(destino, 'JPEG', quality=85, optimize=True)
                foto_ruta = f"uploads/{filename}"
            except Exception as e:
                flash(f'Error al procesar la imagen: {str(e)}', 'danger')
                return render_template('publicar.html', nombre=nombre, descripcion=descripcion, precio=precio,
                                       edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                       numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)
        elif foto and foto.filename != '':
            # Procesar archivo tradicional
            if not allowed_file(foto.filename):
                flash('El archivo de imagen debe ser PNG, JPG, JPEG o GIF.', 'danger')
                return render_template('publicar.html', nombre=nombre, descripcion=descripcion, precio=precio,
                                       edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                       numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)
            
            filename = secure_filename(foto.filename)
            timestamp = int(time.time())
            filename = f"{current_user.id}_{timestamp}_{filename}"
            destino = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            foto.save(destino)
            foto_ruta = f"uploads/{filename}"
        
        if not foto_ruta:
            flash('Debes seleccionar y recortar una foto del animal.', 'warning')
            return render_template('publicar.html', nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        try:
            precio_valor = int(precio)
            if precio_valor < 10000 or precio_valor > 999999:
                raise ValueError()
        except ValueError:
            flash('Ingresa un precio entero de 5 a 6 dígitos.', 'danger')
            return render_template('publicar.html', nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        try:
            edad_valor = int(edad)
            if edad_valor < 0:
                raise ValueError()
        except ValueError:
            flash('Ingresa una edad numérica válida.', 'danger')
            return render_template('publicar.html', nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        try:
            peso_valor = float(peso)
            if peso_valor <= 0:
                raise ValueError()
        except ValueError:
            flash('Ingresa un peso numérico válido.', 'danger')
            return render_template('publicar.html', nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        try:
            tamano_valor = float(tamano)
            if tamano_valor <= 0:
                raise ValueError()
        except ValueError:
            flash('Ingresa un tamaño numérico válido.', 'danger')
            return render_template('publicar.html', nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        servicios_valor = None
        if numero_servicios.isdigit():
            servicios_valor = int(numero_servicios)

        nuevo_producto = Producto(
            nombre=nombre,
            descripcion=descripcion,
            precio=precio_valor,
            tipo=tipo,
            foto=foto_ruta,
            edad=str(edad_valor),
            peso=str(peso_valor),
            tamano=str(tamano_valor),
            raza=raza,
            color=color,
            numero_servicios=servicios_valor,
            numero_carabana=numero_carabana or None,
            senal=senal or None,
            usuario_id=current_user.id
        )
        db.session.add(nuevo_producto)
        db.session.commit()

        flash('Animal publicado correctamente.', 'success')
        return redirect(url_for('publicar'))

    return render_template('publicar.html')

@app.route('/ferias', methods=['GET', 'POST'])
def ferias():
    if request.method == 'POST':
        if not current_user.is_authenticated:
            flash('Inicia sesión para registrar ferias y eventos.', 'warning')
            return redirect(url_for('login'))

        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        fecha_str = request.form.get('fecha', '').strip()
        ubicacion = request.form.get('ubicacion', '').strip()

        if not nombre or not fecha_str:
            flash('El nombre y la fecha son obligatorios.', 'warning')
            return redirect(url_for('ferias'))

        try:
            fecha = datetime.fromisoformat(fecha_str)
            if fecha.date() < datetime.now().date():
                raise ValueError('La fecha debe ser posterior a hoy.')
        except Exception:
            flash('Ingresa una fecha válida y futura.', 'danger')
            return redirect(url_for('ferias'))

        nuevo_evento = Evento(
            nombre=nombre,
            descripcion=descripcion,
            fecha=fecha,
            ubicacion=ubicacion
        )
        db.session.add(nuevo_evento)
        db.session.commit()
        flash('Evento registrado correctamente.', 'success')
        return redirect(url_for('ferias'))

    eventos = Evento.query.order_by(Evento.fecha).all()
    eventos_json = [
        {
            'id': evento.id,
            'nombre': evento.nombre,
            'descripcion': evento.descripcion or '',
            'fecha': evento.fecha.isoformat(),
            'ubicacion': evento.ubicacion or ''
        }
        for evento in eventos
    ]
    return render_template(
        'ferias.html',
        eventos=eventos,
        eventos_json=eventos_json,
        authenticated=current_user.is_authenticated,
        min_date=datetime.now().date().isoformat()
    )

@app.route('/reproductores')
def reproductores():
    productos = Producto.query.filter_by(tipo='reproductor').all()
    return render_template('productos.html', productos=productos, titulo='Reproductores en Venta')

@app.route('/producto/<int:producto_id>')
def detalle_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    return render_template('producto_detalle.html', producto=producto)

@app.route('/producto/<int:producto_id>/quitar_venta', methods=['POST'])
@login_required
def quitar_venta(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    if producto.usuario_id != current_user.id:
        abort(403)

    nombre_producto = producto.nombre
    db.session.delete(producto)
    db.session.commit()

    flash(f'El animal "{nombre_producto}" ya no está en venta.', 'success')
    return redirect(url_for('registro_animales'))

@app.route('/producto/<int:producto_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_producto(producto_id):
    producto = Producto.query.get_or_404(producto_id)
    if producto.usuario_id != current_user.id:
        abort(403)

    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        precio = request.form.get('precio', '').strip()
        edad = request.form.get('edad', '').strip()
        peso = request.form.get('peso', '').strip()
        tamano = request.form.get('tamano', '').strip()
        raza = request.form.get('raza', '').strip()
        color = request.form.get('color', '').strip()
        numero_servicios = request.form.get('numero_servicios', '').strip()
        numero_carabana = request.form.get('numero_carabana', '').strip()
        senal = request.form.get('senal', '').strip()

        if not nombre or not precio or not edad or not peso or not tamano or not raza or not color:
            flash('Completa todos los campos obligatorios.', 'warning')
            return render_template('editar_producto.html', producto=producto,
                                   nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        foto = request.files.get('foto')
        foto_base64 = request.form.get('foto', '').strip()
        
        if foto_base64 and foto_base64.startswith('data:image'):
            # Procesar imagen base64 (recortada)
            try:
                # Extraer el base64 del data URL
                header, encoded = foto_base64.split(',', 1)
                image_data = base64.b64decode(encoded)
                image = Image.open(io.BytesIO(image_data))
                
                # Generar nombre de archivo
                filename = f"{current_user.id}_{int(time.time())}_cropped.jpg"
                destino = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                
                # Guardar como JPEG optimizado
                image.convert('RGB').save(destino, 'JPEG', quality=85, optimize=True)
                producto.foto = f"uploads/{filename}"
            except Exception as e:
                flash(f'Error al procesar la imagen: {str(e)}', 'danger')
                return render_template('editar_producto.html', producto=producto,
                                       nombre=nombre, descripcion=descripcion, precio=precio,
                                       edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                       numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)
        elif foto and foto.filename != '':
            # Procesar archivo tradicional
            if not allowed_file(foto.filename):
                flash('El archivo de imagen debe ser PNG, JPG, JPEG o GIF.', 'danger')
                return render_template('editar_producto.html', producto=producto,
                                       nombre=nombre, descripcion=descripcion, precio=precio,
                                       edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                       numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)
            filename = secure_filename(foto.filename)
            timestamp = int(time.time())
            filename = f"{current_user.id}_{timestamp}_{filename}"
            destino = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            foto.save(destino)
            producto.foto = f"uploads/{filename}"

        try:
            precio_valor = int(precio)
            if precio_valor < 10000 or precio_valor > 999999:
                raise ValueError()
        except ValueError:
            flash('Ingresa un precio entero de 5 a 6 dígitos.', 'danger')
            return render_template('editar_producto.html', producto=producto,
                                   nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        try:
            edad_valor = int(edad)
            if edad_valor < 0:
                raise ValueError()
        except ValueError:
            flash('Ingresa una edad numérica válida.', 'danger')
            return render_template('editar_producto.html', producto=producto,
                                   nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        try:
            peso_valor = float(peso)
            if peso_valor <= 0:
                raise ValueError()
        except ValueError:
            flash('Ingresa un peso numérico válido.', 'danger')
            return render_template('editar_producto.html', producto=producto,
                                   nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        try:
            tamano_valor = float(tamano)
            if tamano_valor <= 0:
                raise ValueError()
        except ValueError:
            flash('Ingresa un tamaño numérico válido.', 'danger')
            return render_template('editar_producto.html', producto=producto,
                                   nombre=nombre, descripcion=descripcion, precio=precio,
                                   edad=edad, peso=peso, tamano=tamano, raza=raza, color=color,
                                   numero_servicios=numero_servicios, numero_carabana=numero_carabana, senal=senal)

        producto.nombre = nombre
        producto.descripcion = descripcion
        producto.precio = precio_valor
        producto.edad = str(edad_valor)
        producto.peso = str(peso_valor)
        producto.tamano = str(tamano_valor)
        producto.raza = raza
        producto.color = color
        producto.numero_servicios = int(numero_servicios) if numero_servicios.isdigit() else None
        producto.numero_carabana = numero_carabana or None
        producto.senal = senal or None

        db.session.commit()
        flash('Animal actualizado correctamente.', 'success')
        return redirect(url_for('detalle_producto', producto_id=producto.id))

    return render_template('editar_producto.html', producto=producto)

@app.route('/ganadores')
def ganadores():
    productos = Producto.query.filter_by(tipo='ganador').all()
    return render_template('productos.html', productos=productos, titulo='Ganadores y Resultados')

@app.route('/productores')
def productores():
    usuarios = User.query.filter_by(tipo_usuario='vendedor').all()
    return render_template('productores.html', productores=usuarios)

@app.route('/productores/<int:user_id>')
def productor_venta(user_id):
    usuario = User.query.get_or_404(user_id)
    productos = Producto.query.filter_by(usuario_id=usuario.id).all()
    titulo = f'Productos de {usuario.username}'
    return render_template('productos.html', productos=productos, titulo=titulo)

@app.route('/consejos')
def consejos():
    query = request.args.get('q', '').strip()
    consejos_query = Consejo.query
    subconejos_query = SubConsejoMarkdown.query
    
    if query:
        pattern = f"%{query}%"
        
        # Buscar en categorías
        consejos_query = consejos_query.filter(
            or_(
                Consejo.contenido.ilike(pattern),
                Consejo.categoria.ilike(pattern)
            )
        )
        
        # Buscar en artículos
        subconejos_query = subconejos_query.filter(
            or_(
                SubConsejoMarkdown.titulo.ilike(pattern),
                SubConsejoMarkdown.contenido.ilike(pattern)
            )
        )
    
    consejos = consejos_query.order_by(Consejo.id.desc()).all()
    subconejos = subconejos_query.order_by(SubConsejoMarkdown.orden).all()
    
    return render_template('consejos.html', consejos=consejos, subconejos=subconejos, query=query)

@app.route('/consejos/<int:consejo_id>')
def consejo_detalle(consejo_id):
    consejo = Consejo.query.get_or_404(consejo_id)
    query = request.args.get('q', '').strip()
    
    subconejos_query = SubConsejoMarkdown.query.filter_by(consejo_id=consejo_id)
    
    if query:
        pattern = f"%{query}%"
        subconejos_query = subconejos_query.filter(
            or_(
                SubConsejoMarkdown.titulo.ilike(pattern),
                SubConsejoMarkdown.contenido.ilike(pattern)
            )
        )
    
    subconejos = subconejos_query.order_by(SubConsejoMarkdown.orden).all()
    return render_template('consejos_detalle.html', consejo=consejo, subconejos=subconejos, query=query)

@app.route('/consejos/<int:consejo_id>/subconsejos/<int:sub_id>')
def subconsejos_detalle(consejo_id, sub_id):
    consejo = Consejo.query.get_or_404(consejo_id)
    subconsejos = SubConsejoMarkdown.query.get_or_404(sub_id)
    if subconsejos.consejo_id != consejo_id:
        abort(404)
    return render_template('subconsejos_detalle.html', consejo=consejo, subconsejos=subconsejos)

@app.route('/registro_animales', methods=['GET', 'POST'])
@login_required
def registro_animales():
    if request.method == 'POST':
        # Detectar si es agregar individual o CSV
        if 'archivo_csv' in request.files and request.files['archivo_csv'].filename != '':
            # Importar desde CSV
            archivo = request.files['archivo_csv']
            if not archivo.filename.endswith('.csv'):
                flash('El archivo debe tener extensión .csv', 'danger')
                animales = Animal.query.filter_by(usuario_id=current_user.id).all()
                return render_template('registro_animales.html', animales=animales)
            
            try:
                stream = archivo.stream.read().decode("UTF-8")
                csv_data = csv.DictReader(stream.split('\n'))
                
                animales_importados = 0
                for row in csv_data:
                    if not row or not row.get('nombre'):
                        continue
                    
                    # Validar datos requeridos
                    try:
                        edad_val = int(row.get('edad', 0))
                        peso_val = float(row.get('peso', 0))
                        tamano_val = float(row.get('tamano', 0))
                        
                        nuevo_animal = Animal(
                            nombre=row.get('nombre', '').strip(),
                            edad=str(edad_val),
                            peso=str(peso_val),
                            tamano=str(tamano_val),
                            raza=row.get('raza', 'Tampulli').strip() or 'Tampulli',
                            genero=row.get('genero', 'Macho').strip() or 'Macho',
                            color=row.get('color', '').strip(),
                            numero_servicios=int(row.get('numero_servicios', 0)) if row.get('numero_servicios', '').isdigit() else None,
                            numero_carabana=row.get('numero_carabana', '').strip() or None,
                            senal=row.get('senal', '').strip() or None,
                            descripcion=row.get('descripcion', '').strip() or None,
                            usuario_id=current_user.id
                        )
                        db.session.add(nuevo_animal)
                        animales_importados += 1
                    except (ValueError, KeyError):
                        continue
                
                db.session.commit()
                flash(f'{animales_importados} animales importados correctamente.', 'success')
            except Exception as e:
                flash(f'Error al importar CSV: {str(e)}', 'danger')
            
            return redirect(url_for('registro_animales'))
        else:
            # Agregar animal individual
            nombre = request.form.get('nombre', '').strip()
            edad = request.form.get('edad', '').strip()
            peso = request.form.get('peso', '').strip()
            tamano = request.form.get('tamano', '').strip()
            raza = request.form.get('raza', '').strip()
            genero = request.form.get('genero', '').strip()
            color = request.form.get('color', '').strip()
            numero_servicios = request.form.get('numero_servicios', '').strip()
            numero_carabana = request.form.get('numero_carabana', '').strip()
            senal = request.form.get('senal', '').strip()
            descripcion = request.form.get('descripcion', '').strip()
            
            if not nombre or not edad or not peso or not tamano or not raza or not genero or not color:
                flash('Completa todos los campos obligatorios.', 'warning')
                animales = Animal.query.filter_by(usuario_id=current_user.id).all()
                return render_template('registro_animales.html', animales=animales)
            
            try:
                edad_val = int(edad)
                if edad_val < 0:
                    raise ValueError()
            except ValueError:
                flash('La edad debe ser un número válido.', 'danger')
                animales = Animal.query.filter_by(usuario_id=current_user.id).all()
                return render_template('registro_animales.html', animales=animales)
            
            try:
                peso_val = float(peso)
                if peso_val <= 0:
                    raise ValueError()
            except ValueError:
                flash('El peso debe ser un número válido mayor a 0.', 'danger')
                animales = Animal.query.filter_by(usuario_id=current_user.id).all()
                return render_template('registro_animales.html', animales=animales)
            
            try:
                tamano_val = float(tamano)
                if tamano_val <= 0:
                    raise ValueError()
            except ValueError:
                flash('El tamaño debe ser un número válido mayor a 0.', 'danger')
                animales = Animal.query.filter_by(usuario_id=current_user.id).all()
                return render_template('registro_animales.html', animales=animales)
            
            # Procesar foto si existe
            foto_ruta = None
            foto_base64 = request.form.get('foto', '').strip()
            foto = request.files.get('foto')
            
            if foto_base64 and foto_base64.startswith('data:image'):
                try:
                    header, encoded = foto_base64.split(',', 1)
                    image_data = base64.b64decode(encoded)
                    image = Image.open(io.BytesIO(image_data))
                    filename = f"{current_user.id}_{int(time.time())}_cropped.jpg"
                    destino = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    image.convert('RGB').save(destino, 'JPEG', quality=85, optimize=True)
                    foto_ruta = f"uploads/{filename}"
                except Exception as e:
                    flash(f'Error al procesar la imagen: {str(e)}', 'danger')
                    animales = Animal.query.filter_by(usuario_id=current_user.id).all()
                    return render_template('registro_animales.html', animales=animales)
            elif foto and foto.filename != '':
                if not allowed_file(foto.filename):
                    flash('El archivo de imagen debe ser PNG, JPG, JPEG o GIF.', 'danger')
                    animales = Animal.query.filter_by(usuario_id=current_user.id).all()
                    return render_template('registro_animales.html', animales=animales)
                
                filename = secure_filename(foto.filename)
                timestamp = int(time.time())
                filename = f"{current_user.id}_{timestamp}_{filename}"
                destino = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                foto.save(destino)
                foto_ruta = f"uploads/{filename}"
            
            servicios_valor = None
            if numero_servicios.isdigit():
                servicios_valor = int(numero_servicios)
            
            nuevo_animal = Animal(
                nombre=nombre,
                edad=str(edad_val),
                peso=str(peso_val),
                tamano=str(tamano_val),
                raza=raza,
                genero=genero,
                color=color,
                numero_servicios=servicios_valor,
                numero_carabana=numero_carabana or None,
                senal=senal or None,
                descripcion=descripcion or None,
                foto=foto_ruta,
                usuario_id=current_user.id
            )
            db.session.add(nuevo_animal)
            db.session.commit()
            
            flash('Animal registrado correctamente.', 'success')
            return redirect(url_for('registro_animales'))
    
    animales = Animal.query.filter_by(usuario_id=current_user.id).all()
    return render_template('registro_animales.html', animales=animales)

@app.route('/animal/<int:animal_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if animal.usuario_id != current_user.id:
        abort(403)
    
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        edad = request.form.get('edad', '').strip()
        peso = request.form.get('peso', '').strip()
        tamano = request.form.get('tamano', '').strip()
        raza = request.form.get('raza', '').strip()
        genero = request.form.get('genero', '').strip()
        color = request.form.get('color', '').strip()
        numero_servicios = request.form.get('numero_servicios', '').strip()
        numero_carabana = request.form.get('numero_carabana', '').strip()
        senal = request.form.get('senal', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        
        if not nombre or not edad or not peso or not tamano or not raza or not genero or not color:
            flash('Completa todos los campos obligatorios.', 'warning')
            return render_template('editar_animal.html', animal=animal)
        
        try:
            edad_val = int(edad)
            if edad_val < 0:
                raise ValueError()
        except ValueError:
            flash('La edad debe ser un número válido.', 'danger')
            return render_template('editar_animal.html', animal=animal)
        
        try:
            peso_val = float(peso)
            if peso_val <= 0:
                raise ValueError()
        except ValueError:
            flash('El peso debe ser un número válido mayor a 0.', 'danger')
            return render_template('editar_animal.html', animal=animal)
        
        try:
            tamano_val = float(tamano)
            if tamano_val <= 0:
                raise ValueError()
        except ValueError:
            flash('El tamaño debe ser un número válido mayor a 0.', 'danger')
            return render_template('editar_animal.html', animal=animal)
        
        # Procesar foto si existe
        foto_base64 = request.form.get('foto', '').strip()
        foto = request.files.get('foto')
        
        if foto_base64 and foto_base64.startswith('data:image'):
            try:
                header, encoded = foto_base64.split(',', 1)
                image_data = base64.b64decode(encoded)
                image = Image.open(io.BytesIO(image_data))
                filename = f"{current_user.id}_{int(time.time())}_cropped.jpg"
                destino = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                image.convert('RGB').save(destino, 'JPEG', quality=85, optimize=True)
                animal.foto = f"uploads/{filename}"
            except Exception as e:
                flash(f'Error al procesar la imagen: {str(e)}', 'danger')
                return render_template('editar_animal.html', animal=animal)
        elif foto and foto.filename != '':
            if not allowed_file(foto.filename):
                flash('El archivo de imagen debe ser PNG, JPG, JPEG o GIF.', 'danger')
                return render_template('editar_animal.html', animal=animal)
            
            filename = secure_filename(foto.filename)
            timestamp = int(time.time())
            filename = f"{current_user.id}_{timestamp}_{filename}"
            destino = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            foto.save(destino)
            animal.foto = f"uploads/{filename}"
        
        animal.nombre = nombre
        animal.edad = str(edad_val)
        animal.peso = str(peso_val)
        animal.tamano = str(tamano_val)
        animal.raza = raza
        animal.genero = genero
        animal.color = color
        animal.numero_servicios = int(numero_servicios) if numero_servicios.isdigit() else None
        animal.numero_carabana = numero_carabana or None
        animal.senal = senal or None
        animal.descripcion = descripcion or None
        animal.fecha_modificacion = datetime.now()

        # Intentar guardar y capturar errores para diagnóstico
        try:
            db.session.commit()
            flash('Animal actualizado correctamente.', 'success')
            return redirect(url_for('registro_animales'))
        except Exception as e:
            db.session.rollback()
            # Mostrar datos recibidos y el error para ayudar a depurar
            flash(f'Error al guardar cambios: {str(e)}', 'danger')
            flash(f'Datos recibidos - nombre: {nombre}, raza: {raza}, genero: {genero}, foto_subida: {bool(foto)}, foto_base64: {bool(foto_base64)}', 'warning')
            return render_template('editar_animal.html', animal=animal)
    
    return render_template('editar_animal.html', animal=animal)

@app.route('/animal/<int:animal_id>/eliminar', methods=['POST'])
@login_required
def eliminar_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if animal.usuario_id != current_user.id:
        abort(403)
    
    nombre_animal = animal.nombre
    db.session.delete(animal)
    db.session.commit()
    
    flash(f'Animal "{nombre_animal}" eliminado correctamente.', 'success')
    return redirect(url_for('registro_animales'))

@app.route('/animal/<int:animal_id>/vender', methods=['GET', 'POST'])
@login_required
def vender_animal(animal_id):
    animal = Animal.query.get_or_404(animal_id)
    if animal.usuario_id != current_user.id:
        abort(403)

    if request.method == 'POST':
        precio = request.form.get('precio', '').strip()
        descripcion = request.form.get('descripcion', '').strip() or animal.descripcion or ''

        if not precio:
            flash('Ingresa un precio para poner el animal a la venta.', 'warning')
            return render_template('vender_animal.html', animal=animal, precio=precio, descripcion=descripcion)

        try:
            precio_val = int(precio)
            if precio_val < 10000 or precio_val > 999999:
                raise ValueError()
        except ValueError:
            flash('Ingresa un precio entero válido de 5 a 6 dígitos.', 'danger')
            return render_template('vender_animal.html', animal=animal, precio=precio, descripcion=descripcion)

        ensure_producto_columns()

        producto_existente = Producto.query.filter_by(
            usuario_id=current_user.id,
            nombre=animal.nombre,
            numero_carabana=animal.numero_carabana,
            tipo='reproductor'
        ).first()

        if producto_existente:
            flash('Este animal ya está publicado en venta.', 'warning')
            return redirect(url_for('registro_animales'))

        nuevo_producto = Producto(
            nombre=animal.nombre,
            descripcion=descripcion,
            precio=precio_val,
            tipo='reproductor',
            foto=animal.foto,
            edad=animal.edad,
            peso=animal.peso,
            tamano=animal.tamano,
            raza=animal.raza,
            color=animal.color,
            numero_servicios=animal.numero_servicios,
            numero_carabana=animal.numero_carabana,
            senal=animal.senal,
            usuario_id=current_user.id
        )
        db.session.add(nuevo_producto)
        db.session.commit()

        flash(f'Animal "{animal.nombre}" puesto a la venta correctamente.', 'success')
        return redirect(url_for('reproductores'))

    return render_template('vender_animal.html', animal=animal)

OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'mistral')
OLLAMA_SYSTEM_PROMPT = (
    "Eres un asistente experto en camélidos (alpacas, llamas, vicuñas y guanacos). "
    "Responde en español con consejos prácticos sobre alimentación, salud, reproducción, venta y crianza. "
    "Habla de forma amable y clara. Si no sabes algo, dilo honestamente y recomienda consultar a un especialista."
)
OLLAMA_COMMAND = os.environ.get(
    'OLLAMA_COMMAND',
    r'C:\Users\renzo\AppData\Local\Programs\Ollama\ollama.exe' if os.name == 'nt' else 'ollama'
)


def call_ollama(user_prompt):
    if not user_prompt:
        return None, 'El mensaje no puede estar vacío.'

    prompt = (
        f"{OLLAMA_SYSTEM_PROMPT}\n\n"
        f"Usuario: {user_prompt}\n"
        f"IA: "
    )

    result = subprocess.run(
        [OLLAMA_COMMAND, "run", OLLAMA_MODEL, prompt],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        error_text = result.stderr.strip() or 'Error al ejecutar Ollama.'
        return None, error_text

    return result.stdout.strip(), None


@app.route('/api/chat', methods=['POST'])
def api_chat():
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return {'error': 'Mensaje vacío'}, 400

    response_text, error = call_ollama(message)
    if error:
        return {'error': error}, 500

    return {'response': response_text}


@app.route('/asistente-ia')
def asistente_ia():
    return render_template('asistente_ia.html')


def load_markdown_subconejos():
    """Carga subconejos desde carpetas de consejos_data basadas en categorías."""
    consejos_data_path = os.path.join(app.root_path, 'consejos_data')
    if not os.path.exists(consejos_data_path):
        return
    
    mapeo_categorias = {
        'crianza': 'Crianza',
        'venta': 'Venta',
        'salud': 'Sanidad',
        'alimentacion': 'Alimentación',
        'reproduccion': 'Reproducción',
    }
    
    for folder_name, categoria_nombre in mapeo_categorias.items():
        categoria_path = os.path.join(consejos_data_path, folder_name)
        if not os.path.exists(categoria_path):
            continue
        
        consejo = Consejo.query.filter_by(categoria=categoria_nombre).first()
        if not consejo:
            consejo = Consejo(
                contenido=f'Consejos de {categoria_nombre}.',
                categoria=categoria_nombre,
            )
            db.session.add(consejo)
            db.session.commit()
        
        existing_subs = SubConsejoMarkdown.query.filter_by(consejo_id=consejo.id).count()
        if existing_subs > 0:
            continue
        
        orden = 0

        def procesar_md_folder(source_path, title_hint=None):
            nonlocal orden
            md_files = [f for f in os.listdir(source_path) if f.lower().endswith('.md')]
            if not md_files:
                return

            relative_path = os.path.relpath(source_path, consejos_data_path).replace('\\', '/')
            for md_file in sorted(md_files):
                md_path = os.path.join(source_path, md_file)
                with open(md_path, 'r', encoding='utf-8') as f:
                    contenido_md = f.read()

                titulo_match = re.search(r'^#\s+(.+?)$', contenido_md, re.MULTILINE)
                titulo = titulo_match.group(1) if titulo_match else title_hint or os.path.splitext(md_file)[0].replace('_', ' ').title()

                imagen = None
                img_files = [f for f in os.listdir(source_path) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))]
                if img_files:
                    imagen = f'uploads/consejos/{relative_path}/{img_files[0]}'

                contenido_limpio = re.sub(r'^\*"[^\"]*\.(jpg|jpeg|png|gif)"\*\s*$', '', contenido_md, flags=re.MULTILINE | re.IGNORECASE)
                contenido_limpio = re.sub(r'^\*"?[A-Z]:\\[^\"]*\.(jpg|jpeg|png|gif)"?\*?\s*$', '', contenido_limpio, flags=re.MULTILINE | re.IGNORECASE)
                contenido_limpio = re.sub(r'!\[.*?\]\([^)]*\.(jpg|jpeg|png|gif)\)', '', contenido_limpio, flags=re.IGNORECASE)

                contenido_html = markdown.markdown(contenido_limpio)

                sub = SubConsejoMarkdown(
                    consejo_id=consejo.id,
                    titulo=titulo,
                    contenido=contenido_html,
                    imagen=imagen,
                    orden=orden
                )
                db.session.add(sub)
                orden += 1

        procesar_md_folder(categoria_path, title_hint=categoria_nombre)

        for subfolder in sorted(os.listdir(categoria_path)):
            subfolder_path = os.path.join(categoria_path, subfolder)
            if not os.path.isdir(subfolder_path):
                continue

            procesar_md_folder(subfolder_path, title_hint=subfolder.replace('_', ' ').title())

        db.session.commit()

def seed_default_consejos():
    existing = Consejo.query.first()
    if existing:
        return

    ejemplos = [
        {
            'contenido': 'Ofrece forraje de calidad, heno limpio y agua fresca. Ajusta la dieta según la edad, condición y carga productiva.',
            'categoria': 'Alimentación',
        },
        {
            'contenido': 'Limpia los corrales diariamente y evita acumulación de estiércol. Mantén una cama seca y ventilación adecuada para reducir enfermedades respiratorias.',
            'categoria': 'Sanidad',
        },
        {
            'contenido': 'Evalúa la conformación, temperamento, salud y rendimiento genético antes de seleccionar reproductores para mejorar tu rebaño.',
            'categoria': 'Reproducción',
        },
        {
            'contenido': 'Describe claramente las condiciones del animal, su edad, peso y antecedentes sanitarios para generar confianza en los compradores.',
            'categoria': 'Venta',
        },
        {
            'contenido': 'Asegura una lactancia completa y un ambiente limpio. Introduce concentrados gradualmente para evitar problemas digestivos.',
            'categoria': 'Crianza',
        },
    ]

    for item in ejemplos:
        consejo = Consejo(
            contenido=item['contenido'],
            categoria=item['categoria'],
        )
        db.session.add(consejo)
    db.session.commit()


def sync_global_sources_from_json():
    json_path = os.path.join(app.root_path, 'news_sources.json')
    if not os.path.exists(json_path):
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            urls = data.get('urls', []) if isinstance(data, dict) else data
            urls = [u.strip() for u in urls if isinstance(u, str) and u.strip()]

        existing_sources = {g.url: g for g in GlobalNewsSource.query.all()}
        for url, source in existing_sources.items():
            if url not in urls:
                try:
                    NewsItem.query.filter_by(global_source_id=source.id).delete(synchronize_session=False)
                except Exception:
                    pass
                db.session.delete(source)

        for url in urls:
            if url not in existing_sources:
                db.session.add(GlobalNewsSource(url=url))

        db.session.commit()
    except Exception:
        pass

def initialize_app():
    with app.app_context():
        try:
            db.create_all()
        except Exception:
            pass

        try:
            ensure_producto_columns()
        except Exception:
            pass

        ensure_user_columns()

        try:
            seed_default_consejos()
        except Exception:
            pass

        try:
            load_markdown_subconejos()
        except Exception:
            pass

        try:
            sync_global_sources_from_json()
        except Exception:
            pass

        if not VERCEL_DEPLOY:
            try:
                update_all_sources()
            except Exception:
                pass

initialize_app()

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.environ.get('PORT', 5000)),
        debug=os.environ.get('FLASK_DEBUG', 'False').lower() in ('1', 'true', 'yes')
    )
