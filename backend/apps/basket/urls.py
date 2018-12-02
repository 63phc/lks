from django.conf.urls import url
from django.contrib.auth.decorators import login_required

from .views import BasketView, BasketAddView, VoucherAddView, \
    VoucherRemoveView, SavedView

urlpatterns = [
    url(r'^$', BasketView.as_view(), name='summary'),
    url(r'^add/(?P<pk>\d+)/$', BasketAddView.as_view(), name='add'),
    url(r'^vouchers/add/$', VoucherAddView.as_view(), name='vouchers-add'),
    url(r'^vouchers/(?P<pk>\d+)/remove/$',
        VoucherRemoveView.as_view(), name='vouchers-remove'),
    url(r'^saved/$', login_required(SavedView.as_view()), name='saved'),
]
