from deprepagos.settings import *
import os

DEBUG = False

# Render sets this automatically; also allow custom domain
RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME', '')
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
# Add any custom domain here:
# ALLOWED_HOSTS.append('tu-dominio.com')

CSRF_TRUSTED_ORIGINS = [f'https://{RENDER_EXTERNAL_HOSTNAME}'] if RENDER_EXTERNAL_HOSTNAME else []

# Disable email verification — no email provider configured yet
ACCOUNT_EMAIL_VERIFICATION = 'none'
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# Static files served by WhiteNoise (no S3 needed)
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files — Google Cloud Storage (only enabled when credentials are present)
_gcs_credentials_path = os.environ.get('GCS_CREDENTIALS_FILE', '/etc/secrets/gcs-credentials.json')
_gcs_bucket = os.environ.get('GCS_BUCKET_NAME', '')
if os.path.exists(_gcs_credentials_path) and _gcs_bucket:
    from google.oauth2 import service_account
    GS_CREDENTIALS = service_account.Credentials.from_service_account_file(_gcs_credentials_path)
    GS_BUCKET_NAME = _gcs_bucket
    GS_DEFAULT_ACL = 'publicRead'
    GS_FILE_OVERWRITE = False
    DEFAULT_FILE_STORAGE = 'storages.backends.gcloud.GoogleCloudStorage'
    MEDIA_URL = f'https://storage.googleapis.com/{_gcs_bucket}/'
