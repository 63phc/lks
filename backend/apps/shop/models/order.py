from django.db import models
from django.utils.translation import ugettext_lazy as _


class Order(models.Model):
    user = models.ForeignKey('User', on_delete=models.deletion.CASCADE)
    # delivery = models.ForeignKey('Delivery', on_delete=models.deletion.CASCADE)
    promo_code = models.ForeignKey('Promo', on_delete=models.deletion.CASCADE)
    total_price = models.IntegerField(_('Total_price'), null=True, blank=True)
    products =
    created_at =
    payment_type =
    status =
    status_changed_at =
    is_paid =
    