from django.conf import settings
from django.conf.urls import url
from django.contrib import admin
from django.urls import include, path
from django.conf.urls.static import static
from rest_framework import routers
from rest_framework_swagger.views import get_swagger_view

from apps.blog.views import ArticleList, error_404
from apps.shop.api import ProductAPIViewSet


router = routers.DefaultRouter()
router.register(r'api/posts', ArticleList)
router.register(r'api/shop', ProductAPIViewSet)

schema_view = get_swagger_view(title='Shop API')


urlpatterns = [
    path('', include('apps.blog.urls')),
    path('api/docs/', schema_view),
    path('admin/', admin.site.urls),
    path('api-auth/', include('rest_framework.urls', namespace='rest_framework')),
    path('captcha/', include('captcha.urls')),
    path('social/', include('social_django.urls', namespace='social')),
    path('accounts/', include('django.contrib.auth.urls')),
    # path('dashboard/', include('apps.dashboard.urls', namespace='dashboard')),
    path('shop/', include('apps.shop.urls', namespace='shop')),
    path('subscribe/', include('apps.contacts.urls.subscribe', namespace='subscribe')),
    path('tags/', include('apps.tags.urls')),
    path('feedback/', include('apps.contacts.urls.feedback')),
    path('temp/', include('apps.contacts.urls.reviews')),

]

urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
urlpatterns += router.urls


handler404 = error_404

# urlpatterns += [
#     path('google5e682b3d95e1b8ef.html', TemplateView.as_view(template_name='google-auth.html')),
#     path('yandex_5486c91ec180b084.html', TemplateView.as_view(template_name='yandex-auth.html')),
# ]

# http://www.django-rest-framework.org/api-guide/routers/#usage
