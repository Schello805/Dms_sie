import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.environ.get('DMS_DEBUG') == '1'
SECRET_KEY = os.environ.get('DMS_SECRET_KEY', '')
if not SECRET_KEY:
    raise RuntimeError('DMS_SECRET_KEY muss gesetzt sein.')
ALLOWED_HOSTS = os.environ.get('DMS_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
INSTALLED_APPS = ['django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'dms']
MIDDLEWARE = ['dms.system_logs.RequestIdMiddleware','django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware', 'dms.middleware.PrivateContentMiddleware','dms.middleware.ReaderSurfaceMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages','dms.context.navigation']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': os.environ.get('PGDATABASE', 'ims_dms'), 'USER': os.environ.get('PGUSER', 'ims_dms'), 'PASSWORD': os.environ.get('PGPASSWORD', ''), 'HOST': os.environ.get('PGHOST', 'localhost'), 'PORT': os.environ.get('PGPORT', '5432')}}
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'}, {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'}, {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'}, {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE = 'de-de'
TIME_ZONE = 'Europe/Berlin'
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
SESSION_COOKIE_HTTPONLY = True
INTERNAL_HTTP = os.environ.get('DMS_INTERNAL_HTTP') == '1'
SESSION_COOKIE_SECURE = not (DEBUG or INTERNAL_HTTP)
CSRF_COOKIE_SECURE = not (DEBUG or INTERNAL_HTTP)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
MEDIA_ROOT = Path(os.environ.get('DMS_MEDIA_ROOT', str(BASE_DIR / 'media')))
DATA_UPLOAD_MAX_MEMORY_SIZE = 30 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
if os.environ.get('DMS_TRUST_PROXY') == '1':
    # Only enable behind a trusted proxy that overwrites this header.
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECURE_SSL_REDIRECT = not (DEBUG or INTERNAL_HTTP)

SMTP_ENCRYPTION_KEY = os.environ.get('DMS_SMTP_ENCRYPTION_KEY','')

LDAP_ENCRYPTION_KEY = os.environ.get('DMS_LDAP_ENCRYPTION_KEY','')
ERROR_LOG_DIR = Path(os.environ.get('DMS_ERROR_LOG_DIR', str(BASE_DIR / '.local/logs')))
LOGGING = {
    'version':1, 'disable_existing_loggers':False,
    'handlers':{'dms_errors':{'class':'dms.system_logs.SystemErrorHandler','level':'WARNING'}},
    'loggers':{
        'django.request':{'handlers':['dms_errors'],'level':'ERROR','propagate':False},
        'django.security':{'handlers':['dms_errors'],'level':'WARNING','propagate':False},
        'dms':{'handlers':['dms_errors'],'level':'WARNING','propagate':False},
    },
}
