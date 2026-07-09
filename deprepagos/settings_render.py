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

# Media files — for production use S3 or Render Disk
# If using Render Disk, mount at /var/data/media and set:
# MEDIA_ROOT = '/var/data/media'
# DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'
