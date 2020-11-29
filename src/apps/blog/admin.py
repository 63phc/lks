from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from modeltranslation.admin import TranslationAdmin

from src.apps.blog.models import Article, Tag


@admin.register(Tag)
class TagAdmin(TranslationAdmin, admin.ModelAdmin):
    list_display = (
        "title",
        "slug",
    )
    fieldsets = (
        (None, {"fields": ("title", "slug")}),
        (_("SEO"), {"fields": ("title_seo", "meta_keywords", "meta_description")}),
    )


@admin.register(Article)
class ArticleAdmin(TranslationAdmin):
    save_as = True
    save_on_top = True
    list_display = ("pk", "title", "slug")
    list_display_links = ("title",)
    filter_horizontal = ("tags",)
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "title",
                    "slug",
                    "is_active",
                    "image_preview",
                    "author",
                    "tags",
                )
            },
        ),
        (_("Content"), {"fields": ("content",)}),
        (
            _("SEO"),
            {"fields": ("title_seo", "meta_keywords", "meta_description", "image_alt")},
        ),
    )
