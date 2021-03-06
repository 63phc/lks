from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ModelViewSet
from .serializers import ArticleListSerializer, ArticleRetrieveSerializer
from .models import Article


class ArticleList(ModelViewSet):
    queryset = Article.objects.filter(is_active=True).prefetch_related("tags")
    http_method_names = ["get"]
    lookup_field = "slug"

    serializer_classes = {
        "list": ArticleListSerializer,
        "retrieve": ArticleRetrieveSerializer,
    }
    permission_classes = (AllowAny,)

    def get_serializer_class(self):
        return self.serializer_classes.get(self.action, ArticleListSerializer)
