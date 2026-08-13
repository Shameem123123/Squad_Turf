"""
Django settings for the SquadTurf project.
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'dev-only-secret-key-change-before-deploying-to-production'
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '*']

# ---------------------------------------------------------------------------
# Reverse-proxy HTTPS support. Most hosts (Render, Railway, Fly, a Nginx/
# Caddy box, etc.) terminate TLS at the proxy and forward plain HTTP to
# Django, setting X-Forwarded-Proto to tell you the original request was
# HTTPS. Without the line below, Django thinks every request is insecure,
# which breaks the CSRF-protected POSTs that /push/subscribe/ relies on and
# can make cookies behave oddly — a common, easy-to-miss reason "notifications
# don't work" once the app is actually deployed (it's fine on localhost,
# which is why this can go unnoticed until go-live).
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# If you deploy behind a real domain, add it here (or via env var), e.g.
# DJANGO_CSRF_TRUSTED_ORIGINS=https://squadturf.example.com — otherwise the
# browser's Origin header on the push-subscribe POST won't match and Django
# will reject it with a 403 before the subscription ever reaches the server.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',')
    if origin.strip()
]

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'squadturf.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.unread_notifications',
            ],
        },
    },
]

WSGI_APPLICATION = 'squadturf.wsgi.application'
ASGI_APPLICATION = 'squadturf.asgi.application'

# Database
# ---------------------------------------------------------------------------
# IMPORTANT — the "vanishing users" / "settings reset" bug:
# SQLite stores its data as a single file (db.sqlite3) next to the code. Most
# free hosting platforms (Render, Railway, Heroku, etc.) wipe the local
# filesystem on every deploy/restart/scale event — so the DB file (and every
# signup, OTP setting, everything) gets reset to empty. This is NOT a Django
# bug, it's an ephemeral-storage problem.
#
# Fix: point DATABASE_URL at a persistent database (e.g. a free Postgres
# instance from Render/Railway/Supabase/Neon) and this app will use it
# automatically. Locally (no DATABASE_URL set) it keeps using sqlite so nothing
# changes for local dev.
# ---------------------------------------------------------------------------
import dj_database_url

DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600, ssl_require=True)
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'core' / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Auth
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'feed'
LOGOUT_REDIRECT_URL = 'login'

MESSAGE_TAGS = {
    10: 'debug',
    20: 'info',
    25: 'success',
    30: 'warning',
    40: 'error',
}

# ---------------------------------------------------------------------------
# Web Push (VAPID) — this is the mechanism behind "enable notifications":
# it lets the browser show a system notification (like WhatsApp/Instagram)
# even when SquadTurf isn't open in a tab, as long as the browser/OS push
# service is running. On mobile it works best once the site is "Added to
# Home Screen" (see manifest.webmanifest) so the OS treats it like an app.
#
# A working key pair ships below so push works out of the box. For your own
# deployment, generate your own with:
#   python manage.py generate_vapid_keys
# and set these as environment variables instead (never reuse the default
# pair for a real production deployment).
# ---------------------------------------------------------------------------
VAPID_PUBLIC_KEY = os.environ.get(
    'VAPID_PUBLIC_KEY',
    'BG2AC0fhvZb1rAl0E8SglgVce8YaYvqPxGd4LqPjrefMW2UOkjDFFAYohWbjCloSCUGC5p670I7vmdFY4Ijd-d4',
)
VAPID_PRIVATE_KEY = os.environ.get(
    'VAPID_PRIVATE_KEY',
    'nWSuWoDnMe72CydKYez0fKeL0FWcg4lrXbHkrJ5o44w',
)
VAPID_ADMIN_EMAIL = os.environ.get('VAPID_ADMIN_EMAIL', 'admin@example.com')

# ---------------------------------------------------------------------------
# OTP delivery (SMS/WhatsApp). Unset by default -> codes are only logged to
# the server console (core/otp.py: _dispatch_otp), which is why OTPs "don't
# arrive" on a real phone. Set these to route codes through Twilio (SMS or
# WhatsApp) instead — core/otp.py picks this up automatically, no code
# changes needed.
# ---------------------------------------------------------------------------
TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
TWILIO_FROM_NUMBER = os.environ.get('TWILIO_FROM_NUMBER', '')          # SMS, e.g. +1415XXXXXXX
TWILIO_WHATSAPP_FROM = os.environ.get('TWILIO_WHATSAPP_FROM', '')      # e.g. whatsapp:+14155238886

