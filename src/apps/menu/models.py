from django.db import models
from django_extensions.db.fields import AutoSlugField
from mptt.models import MPTTModel, TreeForeignKey
from django.utils.translation import gettext_lazy as _


class Menu(models.Model):
    """
    Category menu
    """

    slug = AutoSlugField(_("slug"), populate_from="title", editable=True)
    hint = models.CharField(_("Hint"), max_length=100)
    is_active = models.BooleanField(_("Active"), default=False)

    def __str__(self):
        return self.slug

    class Meta:
        verbose_name = _("Type")
        verbose_name_plural = _("Types")


class MenuItems(MPTTModel):
    """
    Item menu
    """

    LINK_TARGET_CHOICES = (
        ("_blank", "_blank"),
        ("_top", "_top"),
        ("_parent", "_parent"),
    )
    name = models.CharField(_("Name"), max_length=200, default="")
    url = models.CharField(_("Link"), max_length=200)
    menu = models.ForeignKey(
        "Menu",
        related_name="menu",
        verbose_name=_("Menu type"),
        on_delete=models.PROTECT,
    )
    target = models.CharField(
        max_length=10, choices=LINK_TARGET_CHOICES, blank=True, null=True
    )
    parent = TreeForeignKey(
        "self", null=True, blank=True, related_name="children", on_delete=models.CASCADE
    )
    ordering = models.IntegerField(_("Sort"), default=0)
    is_active = models.BooleanField(_("Active"), default=False)

    def __str__(self):
        return self.name

    class MPTTMeta:
        order_insertion_by = ["name"]

    class Meta:
        verbose_name = _("Menu item")
        verbose_name_plural = _("Menu items")
