from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _


class Order(models.Model):
    """ Order model """
    PAYMENT_CHOICES = (
        ('_paypal', '_paypal'),
        ('_card', '_card'),
    )
    STATUS_CHOICES = (
        ('_choosing', '_choosing'),
        ('_completed', '_completed'),
        ('_sent', '_sent'),
        ('_delivered', '_delivered'),
        ('_lost', '_lost'),
        ('_broken', '_broken'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODE)
    delivery = models.ForeignKey('Delivery', null=True, blank=True)
    promo_code = models.ForeignKey('Promo', null=True, blank=True)
    total_price = models.IntegerField(_('Total_price'), null=True, blank=True)
    products = models.ManyToManyField(_('Products'))
    created_at = models.DateTimeField(_('Created at'), auto_now_add=True)
    payment_type = models.CharField(choices=PAYMENT_CHOICES, null=True, blank=True)
    status = models.CharField(choices=STATUS_CHOICES)
    status_changed_at = models.DateTimeField(_('Status is changed at'))
    is_paid = models.BooleanField(null=True, blank=True)

    class Meta:
        verbose_name = _('Order')
        verbose_name_plural = _('Order')

    def __str__(self):
        return 'Order # ' + str(self.id) + ' by ' + self.user.name
