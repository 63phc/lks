
INSTALLED_APPS = [
    'modeltranslation',
    
    # Django core
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    # 'django.contrib.sites',

    # Plugins
    'corsheaders',
    'django_extensions',
    'mptt',
    
    'debug_toolbar',
    'social_django',
    # 'captcha',
    'ckeditor',
    'ckeditor_uploader',
    'optimized_image',
    'djmoney',
    'colorful',
    # 'crispy_forms',
    
    # Django Rest Framework
    'rest_framework',
    'rest_framework_swagger',
    'rest_framework_simplejwt.token_blacklist',
    'drf_yasg',
    
    # Apps project
    'src.apps.api',
    'src.apps.blog',
    'src.apps.shop',
    'src.apps.menu',
    'src.apps.account',
    'src.apps.subscribe',
    # 'src.apps.contacts',
    'src.apps.slider',
]

