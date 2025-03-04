from pathlib import Path
import os
import dj_database_url

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Stripe Keys
STRIPE_PUBLIC_KEY = os.getenv("pk_live_51QoMKjJYDgv8Jx3VXa5Vl07vwlhb0xMnrK0Jm9pO4T2YxGX9Wb3WN48LWWEAkGnXguh9Z6hC5kAygaqncQchbzJe00huvjYgCH", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "price_1QpQcMJYDgv8Jx3VdIdRmwsL")
STRIPE_WEBHOOK_SECRET = os.getenv("whsec_wT7g2urYrVwg96Tqv9AvBLwfqejaqQhS", "")

# settings.py
RECAPTCHA_SITE_KEY = '6Lf2tuAqAAAAAJQf5hVLPgoyF-38eAybdJVRBA_W'
RECAPTCHA_SECRET_KEY = '6Lf2tuAqAAAAACNaUMmTeo34l3CtbM6fy5QwK3TE'

GEMINI_API_KEY = 'AIzaSyAhBjjphW7nVHETfDtewuy_qiFXspa1yO4'



# Security Settings
SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-key")
DEBUG = True

ALLOWED_HOSTS = ["*"] if DEBUG else [
    "pavonify.com",
    "www.pavonify.com",
    "pavonify-production.up.railway.app",
    ".railway.app",
]

CSRF_TRUSTED_ORIGINS = [
    "https://pavonify-production.up.railway.app",
    "https://pavonify.com",  # ✅ Fix missing comma
    "https://www.pavonify.com",
]

X_FRAME_OPTIONS = 'SAMEORIGIN'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    'learning',  # Your main app
    'blog',  # ✅ Add your new blog app
    'django_q',
    'django_countries',
]


# Middleware
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    "whitenoise.middleware.WhiteNoiseMiddleware",  # ✅ Add this here
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# URL Configuration
ROOT_URLCONF = 'lang_platform.urls'

# Template Settings
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / "templates", BASE_DIR / "learning" / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# WSGI Application
WSGI_APPLICATION = 'lang_platform.wsgi.application'

# Database Configuration
DATABASES = {
    'default': dj_database_url.config(
        default=os.getenv('DATABASE_URL', 'sqlite:///db.sqlite3')
    )
}

# Password Validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

# ✅ Add this to tell Django where your original static files are:
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),  # Ensure your favicon is here
]

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# Authentication Settings
AUTH_USER_MODEL = 'learning.User'
LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/teacher-dashboard/'

# Session Settings
SESSION_ENGINE = "django.contrib.sessions.backends.cache"
SESSION_CACHE_ALIAS = "default"

# Enforce HTTPS
SECURE_SSL_REDIRECT = False  # ✅ Only redirect if NOT in DEBUG mode
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Default Primary Key Field
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django-Q Configuration
Q_CLUSTER = {
    "name": "DjangoQ",
    "workers": 4,
    "recycle": 500,
    "timeout": 60,   
    "retry": 90,
    "django_redis": "default",
    "ack_failures": True,
    "orm": "default",
}
