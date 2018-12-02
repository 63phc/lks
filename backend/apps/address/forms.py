from django import forms
from django.conf import settings

from backend.apps.address.models import UserAddress


class AddressForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        """
        Set fields in OSCAR_REQUIRED_ADDRESS_FIELDS as required.
        """
        super().__init__(*args, **kwargs)
        field_names = (set(self.fields)
                       & set(settings.REQUIRED_ADDRESS_FIELDS))
        for field_name in field_names:
            self.fields[field_name].required = True


class UserAddressForm(AddressForm):

    class Meta:
        model = UserAddress
        fields = [
            'title', 'first_name', 'last_name',
            'line1', 'line2', 'line3', 'line4',
            'state', 'postcode', 'country',
            'phone_number', 'notes',
        ]

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.user = user
