import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip("\"'")


load_env(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "django-insecure-development-only")
OMIE_CREDENTIALS_ENCRYPTION_KEY = os.getenv(
    "OMIE_CREDENTIALS_ENCRYPTION_KEY",
    SECRET_KEY,
)
OMIE_API_TIMEOUT = int(os.getenv("OMIE_API_TIMEOUT", "90"))
OMIE_API_RETRIES = int(os.getenv("OMIE_API_RETRIES", "3"))
OMIE_API_RETRY_DELAY = int(os.getenv("OMIE_API_RETRY_DELAY", "2"))
OMIE_API_REDUNDANT_DELAY = int(os.getenv("OMIE_API_REDUNDANT_DELAY", "60"))
OMIE_API_REDUNDANT_BUFFER = int(os.getenv("OMIE_API_REDUNDANT_BUFFER", "5"))
DATA_UPLOAD_MAX_NUMBER_FIELDS = int(
    os.getenv("DATA_UPLOAD_MAX_NUMBER_FIELDS", "50000")
)
DEBUG = os.getenv("DEBUG", "True").lower() in {"1", "true", "yes"}
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}"
        for host in ALLOWED_HOSTS
        if host not in {"127.0.0.1", "localhost"} and not host.startswith(".")
    ]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)

APP_BRAND_NAME = os.getenv("APP_BRAND_NAME", "MD21 BI")
APP_BRAND_NAVBAR_TEXT = os.getenv("APP_BRAND_NAVBAR_TEXT", "MD21 BI")
APP_BRAND_LOGIN_LOGO = os.getenv("APP_BRAND_LOGIN_LOGO", "logo_elevdata_semfundo.png")
APP_BRAND_NAVBAR_LOGO = os.getenv("APP_BRAND_NAVBAR_LOGO", "logo_elevdata_new.jpg")
APP_BRAND_HERO_EYEBROW = os.getenv("APP_BRAND_HERO_EYEBROW", "BEM-VINDO")
APP_BRAND_HERO_TITLE = os.getenv(
    "APP_BRAND_HERO_TITLE",
    "Dados claros e<br>decis&otilde;es melhores.",
)
APP_BRAND_HERO_SUBTITLE = os.getenv(
    "APP_BRAND_HERO_SUBTITLE",
    "Uma visao completa da sua operacao, do comercial ao financeiro, em um so lugar.",
)
APP_BRAND_REGISTER_EYEBROW = os.getenv(
    "APP_BRAND_REGISTER_EYEBROW",
    "MD21 BUSINESS INTELLIGENCE",
)
APP_BRAND_REGISTER_TITLE = os.getenv(
    "APP_BRAND_REGISTER_TITLE",
    "Sua empresa<br>vista por inteiro.",
)
APP_BRAND_REGISTER_SUBTITLE = os.getenv(
    "APP_BRAND_REGISTER_SUBTITLE",
    "Crie sua conta para acessar indicadores comerciais, financeiros, compras, estoque e CRM.",
)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.empresas",
    "apps.dashboards",
    "apps.comercial",
    "apps.financeiro",
    "apps.compras",
    "apps.estoque",
    "apps.crm",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.brand",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"

DATABASE_ENGINE = os.getenv("DATABASE_ENGINE", "sqlite").lower()

if DATABASE_ENGINE in {"postgres", "postgresql"}:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "west_bi"),
            "USER": os.getenv("POSTGRES_USER", "postgres"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("POSTGRES_CONN_MAX_AGE", "60")),
            "OPTIONS": {
                "connect_timeout": int(os.getenv("POSTGRES_CONNECT_TIMEOUT", "10")),
            },
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
            "OPTIONS": {
                "timeout": 30,
            },
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "pt-br"
TIME_ZONE = "America/Sao_Paulo"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "empresas:lista"
LOGOUT_REDIRECT_URL = "accounts:login"

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() in {"1", "true", "yes"}
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").lower() in {"1", "true", "yes"}
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@localhost")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
