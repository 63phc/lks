import hashlib
import logging
from collections import OrderedDict
from decimal import Decimal as D

from django.conf import settings
from django.conf.global_settings import AUTH_USER_MODEL
from django.core.exceptions import ImproperlyConfigured
from django.core.signing import BadSignature, Signer
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Sum
from django.template import TemplateDoesNotExist, engines
from django.template.loader import get_template
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.utils.translation import pgettext_lazy
from django_extensions.db.fields import AutoSlugField

from apps.basket.models import Option
from .managers import CommunicationTypeManager
from .signals import order_status_changed, order_line_status_changed
from core.utils import get_default_currency
from . import exceptions


logger = logging.getLogger('lks.order')


class Order(models.Model):
    """
    The main order model
    """
    number = models.CharField(
        _("Order number"), max_length=128, db_index=True, unique=True)

    basket = models.ForeignKey(
        'basket.Basket', verbose_name=_("Basket"),
        null=True, blank=True, on_delete=models.SET_NULL)

    # Orders can be placed without the user authenticating so we don't always
    # have a customer ID.
    user = models.ForeignKey(
        AUTH_USER_MODEL, related_name='orders', null=True, blank=True,
        verbose_name=_("User"), on_delete=models.SET_NULL)

    # Billing address is not always required (eg paying by gift card)
    billing_address = models.ForeignKey(
        'BillingAddress', null=True, blank=True,
        verbose_name=_("Billing Address"),
        on_delete=models.SET_NULL)

    # Total price looks like it could be calculated by adding up the
    # prices of the associated lines, but in some circumstances extra
    # order-level charges are added and so we need to store it separately
    currency = models.CharField(
        _("Currency"), max_length=12, default=get_default_currency)
    total_incl_tax = models.DecimalField(
        _("Order total (inc. tax)"), decimal_places=2, max_digits=12)
    total_excl_tax = models.DecimalField(
        _("Order total (excl. tax)"), decimal_places=2, max_digits=12)

    # Shipping charges
    shipping_incl_tax = models.DecimalField(
        _("Shipping charge (inc. tax)"), decimal_places=2, max_digits=12,
        default=0)
    shipping_excl_tax = models.DecimalField(
        _("Shipping charge (excl. tax)"), decimal_places=2, max_digits=12,
        default=0)

    # Not all lines are actually shipped (such as downloads), hence shipping
    # address is not mandatory.
    shipping_address = models.ForeignKey(
        'ShippingAddress', null=True, blank=True,
        verbose_name=_("Shipping Address"),
        on_delete=models.SET_NULL)
    shipping_method = models.CharField(
        _("Shipping method"), max_length=128, blank=True)

    # Identifies shipping code
    shipping_code = models.CharField(blank=True, max_length=128, default="")

    # Use this field to indicate that an order is on hold / awaiting payment
    status = models.CharField(_("Status"), max_length=100, blank=True)
    guest_email = models.EmailField(_("Guest email address"), blank=True)

    # Index added to this field for reporting
    date_placed = models.DateTimeField(db_index=True)

    @classmethod
    def all_statuses(cls):
        """
        Return all possible statuses for an order
        """
        return list(cls.pipeline.keys())

    def available_statuses(self):
        """
        Return all possible statuses that this order can move to
        """
        return self.pipeline.get(self.status, ())

    def set_status(self, new_status):
        """
        Set a new status for this order.

        If the requested status is not valid, then ``InvalidOrderStatus`` is
        raised.
        """
        if new_status == self.status:
            return

        old_status = self.status

        if new_status not in self.available_statuses():
            raise exceptions.InvalidOrderStatus(
                _("'%(new_status)s' is not a valid status for order %(number)s"
                  " (current status: '%(status)s')")
                % {'new_status': new_status,
                   'number': self.number,
                   'status': self.status})
        self.status = new_status
        if new_status in self.cascade:
            for line in self.lines.all():
                line.status = self.cascade[self.status]
                line.save()
        self.save()

        # Send signal for handling status changed
        order_status_changed.send(sender=self,
                                  order=self,
                                  old_status=old_status,
                                  new_status=new_status,
                                  )

        self._create_order_status_change(old_status, new_status)

    set_status.alters_data = True

    def _create_order_status_change(self, old_status, new_status):
        # Not setting the status on the order as that should be handled before
        self.status_changes.create(old_status=old_status, new_status=new_status)

    @property
    def is_anonymous(self):
        # It's possible for an order to be placed by a customer who then
        # deletes their profile.  Hence, we need to check that a guest email is
        # set.
        return self.user is None and bool(self.guest_email)

    @property
    def basket_total_before_discounts_incl_tax(self):
        """
        Return basket total including tax but before discounts are applied
        """
        total = D('0.00')
        for line in self.lines.all():
            total += line.line_price_before_discounts_incl_tax
        return total

    @property
    def basket_total_before_discounts_excl_tax(self):
        """
        Return basket total excluding tax but before discounts are applied
        """
        total = D('0.00')
        for line in self.lines.all():
            total += line.line_price_before_discounts_excl_tax
        return total

    @property
    def basket_total_incl_tax(self):
        """
        Return basket total including tax
        """
        return self.total_incl_tax - self.shipping_incl_tax

    @property
    def basket_total_excl_tax(self):
        """
        Return basket total excluding tax
        """
        return self.total_excl_tax - self.shipping_excl_tax

    @property
    def total_before_discounts_incl_tax(self):
        return (self.basket_total_before_discounts_incl_tax
                + self.shipping_incl_tax)

    @property
    def total_before_discounts_excl_tax(self):
        return (self.basket_total_before_discounts_excl_tax
                + self.shipping_excl_tax)

    @property
    def total_discount_incl_tax(self):
        """
        The amount of discount this order received
        """
        discount = D('0.00')
        for line in self.lines.all():
            discount += line.discount_incl_tax
        return discount

    @property
    def total_discount_excl_tax(self):
        discount = D('0.00')
        for line in self.lines.all():
            discount += line.discount_excl_tax
        return discount

    @property
    def total_tax(self):
        return self.total_incl_tax - self.total_excl_tax

    @property
    def num_lines(self):
        return self.lines.count()

    @property
    def num_items(self):
        """
        Returns the number of items in this order.
        """
        num_items = 0
        for line in self.lines.all():
            num_items += line.quantity
        return num_items

    @property
    def shipping_tax(self):
        return self.shipping_incl_tax - self.shipping_excl_tax

    @property
    def shipping_status(self):
        """Return the last complete shipping event for this order."""

        # As safeguard against identical timestamps, also sort by the primary
        # key. It's not recommended to rely on this behaviour, but in practice
        # reasonably safe if PKs are not manually set.
        events = self.shipping_events.order_by('-date_created', '-pk').all()
        if not len(events):
            return ''

        # Collect all events by event-type
        event_map = OrderedDict()
        for event in events:
            event_name = event.event_type.name
            if event_name not in event_map:
                event_map[event_name] = []
            event_map[event_name].extend(list(event.line_quantities.all()))

        # Determine last complete event
        status = _("In progress")
        for event_name, event_line_quantities in event_map.items():
            if self._is_event_complete(event_line_quantities):
                return event_name
        return status

    @property
    def has_shipping_discounts(self):
        return len(self.shipping_discounts) > 0

    @property
    def shipping_before_discounts_incl_tax(self):
        # We can construct what shipping would have been before discounts by
        # adding the discounts back onto the final shipping charge.
        total = D('0.00')
        for discount in self.shipping_discounts:
            total += discount.amount
        return self.shipping_incl_tax + total

    def _is_event_complete(self, event_quantities):
        # Form map of line to quantity
        event_map = {}
        for event_quantity in event_quantities:
            line_id = event_quantity.line_id
            event_map.setdefault(line_id, 0)
            event_map[line_id] += event_quantity.quantity

        for line in self.lines.all():
            if event_map.get(line.pk, 0) != line.quantity:
                return False
        return True

    class Meta:
        ordering = ['-date_placed']
        verbose_name = _("Order")
        verbose_name_plural = _("Orders")

    def __str__(self):
        return "#%s" % (self.number,)

    def verification_hash(self):
        signer = Signer(salt='apps.order.Order')
        return signer.sign(self.number)

    def check_verification_hash(self, hash_to_check):
        """
        Checks the received verification hash against this order number.
        Returns False if the verification failed, True otherwise.
        """
        if self.check_deprecated_verification_hash(hash_to_check):
            return True

        signer = Signer(salt='apps.order.Order')
        try:
            signed_number = signer.unsign(hash_to_check)
        except BadSignature:
            return False

        return constant_time_compare(signed_number, self.number)

    @property
    def email(self):
        if not self.user:
            return self.guest_email
        return self.user.email

    def set_date_placed_default(self):
        if self.date_placed is None:
            self.date_placed = now()

    def save(self, *args, **kwargs):
        # Ensure the date_placed field works as it auto_now_add was set. But
        # this gives us the ability to set the date_placed explicitly (which is
        # useful when importing orders from another system).
        self.set_date_placed_default()
        super().save(*args, **kwargs)


class OrderNote(models.Model):
    """
    A note against an order.

    This are often used for audit purposes too.  IE, whenever an admin
    makes a change to an order, we create a note to record what happened.
    """
    order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        related_name="notes",
        verbose_name=_("Order"))

    # These are sometimes programatically generated so don't need a
    # user everytime
    user = models.ForeignKey(
        AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        verbose_name=_("User"))

    # We allow notes to be classified although this isn't always needed
    INFO, WARNING, ERROR, SYSTEM = 'Info', 'Warning', 'Error', 'System'
    note_type = models.CharField(_("Note Type"), max_length=128, blank=True)

    message = models.TextField(_("Message"))
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)
    date_updated = models.DateTimeField(_("Date Updated"), auto_now=True)

    # Notes can only be edited for 5 minutes after being created
    editable_lifetime = 300

    class Meta:
        verbose_name = _("Order Note")
        verbose_name_plural = _("Order Notes")

    def __str__(self):
        return "'%s' (%s)" % (self.message[0:50], self.user)

    def is_editable(self):
        if self.note_type == self.SYSTEM:
            return False
        delta = timezone.now() - self.date_updated
        return delta.seconds < self.editable_lifetime


class OrderStatusChange(models.Model):
    order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        related_name='status_changes',
        verbose_name=_('Order Status Changes')
    )
    old_status = models.CharField(_('Old Status'), max_length=100, blank=True)
    new_status = models.CharField(_('New Status'), max_length=100, blank=True)
    date_created = models.DateTimeField(_('Date Created'), auto_now_add=True)

    class Meta:
        verbose_name = _('Order Status Change')
        verbose_name_plural = _('Order Status Changes')
        ordering = ['-date_created']

    def __str__(self):
        return _('{order} has changed status from {old_status} to {new_status}').format(
            order=self.order, old_status=self.old_status, new_status=self.new_status
        )


class CommunicationEventType(models.Model):
    """
    A 'type' of communication.  Like an order confirmation email.
    """

    #: Code used for looking up this event programmatically.
    # e.g. PASSWORD_RESET. AutoSlugField uppercases the code for us because
    # it's a useful convention that's been enforced in previous Oscar versions
    code = AutoSlugField(
        _('Code'), max_length=128, unique=True, populate_from='name',
        separator="_", editable=True,
        validators=[
            RegexValidator(
                regex=r'^[a-zA-Z_][0-9a-zA-Z_]*$',
                message=_(
                    "Code can only contain the letters a-z, A-Z, digits, "
                    "and underscores, and can't start with a digit."))],
        help_text=_("Code used for looking up this event programmatically"))

    #: Name is the friendly description of an event for use in the admin
    name = models.CharField(
        _('Name'), max_length=255,
        help_text=_("This is just used for organisational purposes"))

    # We allow communication types to be categorised
    # For backwards-compatibility, the choice values are quite verbose
    ORDER_RELATED = 'Order related'
    USER_RELATED = 'User related'
    CATEGORY_CHOICES = (
        (ORDER_RELATED, _('Order related')),
        (USER_RELATED, _('User related'))
    )

    category = models.CharField(
        _('Category'), max_length=255, default=ORDER_RELATED,
        choices=CATEGORY_CHOICES)

    # Template content for emails
    # NOTE: There's an intentional distinction between None and ''. None
    # instructs Oscar to look for a file-based template, '' is just an empty
    # template.
    email_subject_template = models.CharField(
        _('Email Subject Template'), max_length=255, blank=True, null=True)
    email_body_template = models.TextField(
        _('Email Body Template'), blank=True, null=True)
    email_body_html_template = models.TextField(
        _('Email Body HTML Template'), blank=True, null=True,
        help_text=_("HTML template"))

    # Template content for SMS messages
    sms_template = models.CharField(_('SMS Template'), max_length=170,
                                    blank=True, null=True,
                                    help_text=_("SMS template"))

    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)
    date_updated = models.DateTimeField(_("Date Updated"), auto_now=True)

    objects = CommunicationTypeManager()

    # File templates
    email_subject_template_file = 'customer/emails/commtype_%s_subject.txt'
    email_body_template_file = 'customer/emails/commtype_%s_body.txt'
    email_body_html_template_file = 'customer/emails/commtype_%s_body.html'
    sms_template_file = 'customer/sms/commtype_%s_body.txt'

    class Meta:
        verbose_name = _("Communication event type")
        verbose_name_plural = _("Communication event types")

    def get_messages(self, ctx=None):
        """
        Return a dict of templates with the context merged in

        We look first at the field templates but fail over to
        a set of file templates that follow a conventional path.
        """
        code = self.code.lower()

        # Build a dict of message name to Template instances
        templates = {'subject': 'email_subject_template',
                     'body': 'email_body_template',
                     'html': 'email_body_html_template',
                     'sms': 'sms_template'}
        for name, attr_name in templates.items():
            field = getattr(self, attr_name, None)
            if field is not None:
                # Template content is in a model field
                templates[name] = engines['django'].from_string(field)
            else:
                # Model field is empty - look for a file template
                template_name = getattr(self, "%s_file" % attr_name) % code
                try:
                    templates[name] = get_template(template_name)
                except TemplateDoesNotExist:
                    templates[name] = None

        # Pass base URL for serving images within HTML emails
        if ctx is None:
            ctx = {}
        ctx['static_base_url'] = getattr(
            settings, 'OSCAR_STATIC_BASE_URL', None)

        messages = {}
        for name, template in templates.items():
            messages[name] = template.render(ctx) if template else ''

        # Ensure the email subject doesn't contain any newlines
        messages['subject'] = messages['subject'].replace("\n", "")
        messages['subject'] = messages['subject'].replace("\r", "")

        return messages

    def __str__(self):
        return self.name

    def is_order_related(self):
        return self.category == self.ORDER_RELATED

    def is_user_related(self):
        return self.category == self.USER_RELATED


class CommunicationEvent(models.Model):
    """
    An order-level event involving a communication to the customer, such
    as an confirmation email being sent.
    """
    order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        related_name="communication_events",
        verbose_name=_("Order"))
    event_type = models.ForeignKey(
        'CommunicationEventType',
        on_delete=models.CASCADE,
        verbose_name=_("Event Type"))
    date_created = models.DateTimeField(_("Date"), auto_now_add=True)

    class Meta:
        verbose_name = _("Communication Event")
        verbose_name_plural = _("Communication Events")
        ordering = ['-date_created']

    def __str__(self):
        return _("'%(type)s' event for order #%(number)s") \
            % {'type': self.event_type.name, 'number': self.order.number}


# LINES


class Line(models.Model):
    """
    An order line
    """
    order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name=_("Order"))


    # PRODUCT INFORMATION
    # -------------------

    # We don't want any hard links between orders and the products table so we
    # allow this link to be NULLable.
    product = models.ForeignKey(
        'shop.Product', on_delete=models.SET_NULL, blank=True, null=True,
        verbose_name=_("Product"))
    title = models.CharField(
        pgettext_lazy("Product title", "Title"), max_length=255)
    # UPC can be null because it's usually set as the product's UPC, and that
    # can be null as well
    upc = models.CharField(_("UPC"), max_length=128, blank=True, null=True)

    quantity = models.PositiveIntegerField(_("Quantity"), default=1)

    # REPORTING INFORMATION
    # ---------------------

    # Price information (these fields are actually redundant as the information
    # can be calculated from the LinePrice models
    # Deprecated - will be removed in Oscar 2.0
    line_price_incl_tax = models.DecimalField(
        _("Price (inc. tax)"), decimal_places=2, max_digits=12)
    # Deprecated - will be removed in Oscar 2.0
    line_price_excl_tax = models.DecimalField(
        _("Price (excl. tax)"), decimal_places=2, max_digits=12)

    # Price information before discounts are applied
    line_price_before_discounts_incl_tax = models.DecimalField(
        _("Price before discounts (inc. tax)"),
        decimal_places=2, max_digits=12)
    line_price_before_discounts_excl_tax = models.DecimalField(
        _("Price before discounts (excl. tax)"),
        decimal_places=2, max_digits=12)

    # Deprecated - will be removed in Oscar 2.0
    unit_cost_price = models.DecimalField(
        _("Unit Cost Price"), decimal_places=2, max_digits=12, blank=True,
        null=True)
    # Normal site price for item (without discounts)
    unit_price_incl_tax = models.DecimalField(
        _("Unit Price (inc. tax)"), decimal_places=2, max_digits=12,
        blank=True, null=True)
    unit_price_excl_tax = models.DecimalField(
        _("Unit Price (excl. tax)"), decimal_places=2, max_digits=12,
        blank=True, null=True)
    # Deprecated - will be removed in Oscar 2.0
    unit_retail_price = models.DecimalField(
        _("Unit Retail Price"), decimal_places=2, max_digits=12,
        blank=True, null=True)

    # Partners often want to assign some status to each line to help with their
    # own business processes.
    status = models.CharField(_("Status"), max_length=255, blank=True)

    # Deprecated - will be removed in Oscar 2.0
    est_dispatch_date = models.DateField(
        _("Estimated Dispatch Date"), blank=True, null=True)

    class Meta:
        # Enforce sorting in order of creation.
        ordering = ['pk']
        verbose_name = _("Order Line")
        verbose_name_plural = _("Order Lines")

    def __str__(self):
        if self.product:
            title = self.product.title
        else:
            title = _('<missing product>')
        return _("Product '%(name)s', quantity '%(qty)s'") % {
            'name': title, 'qty': self.quantity}

    @classmethod
    def all_statuses(cls):
        """
        Return all possible statuses for an order line
        """
        return list(cls.pipeline.keys())

    def available_statuses(self):
        """
        Return all possible statuses that this order line can move to
        """
        return self.pipeline.get(self.status, ())

    def set_status(self, new_status):
        """
        Set a new status for this line

        If the requested status is not valid, then ``InvalidLineStatus`` is
        raised.
        """
        if new_status == self.status:
            return

        old_status = self.status

        if new_status not in self.available_statuses():
            raise exceptions.InvalidLineStatus(
                _("'%(new_status)s' is not a valid status (current status:"
                  " '%(status)s')")
                % {'new_status': new_status, 'status': self.status})
        self.status = new_status
        self.save()

        # Send signal for handling status changed
        order_line_status_changed.send(sender=self,
                                       line=self,
                                       old_status=old_status,
                                       new_status=new_status,
                                       )

    set_status.alters_data = True

    @property
    def description(self):
        """
        Returns a description of this line including details of any
        line attributes.
        """
        desc = self.title
        ops = []
        for attribute in self.attributes.all():
            ops.append("%s = '%s'" % (attribute.type, attribute.value))
        if ops:
            desc = "%s (%s)" % (desc, ", ".join(ops))
        return desc

    @property
    def discount_incl_tax(self):
        return self.line_price_before_discounts_incl_tax \
            - self.line_price_incl_tax

    @property
    def discount_excl_tax(self):
        return self.line_price_before_discounts_excl_tax \
            - self.line_price_excl_tax

    @property
    def line_price_tax(self):
        return self.line_price_incl_tax - self.line_price_excl_tax

    @property
    def unit_price_tax(self):
        return self.unit_price_incl_tax - self.unit_price_excl_tax

    # Shipping status helpers

    @property
    def shipping_status(self):
        """
        Returns a string summary of the shipping status of this line
        """
        status_map = self.shipping_event_breakdown
        if not status_map:
            return ''

        events = []
        last_complete_event_name = None
        for event_dict in reversed(list(status_map.values())):
            if event_dict['quantity'] == self.quantity:
                events.append(event_dict['name'])
                last_complete_event_name = event_dict['name']
            else:
                events.append("%s (%d/%d items)" % (
                    event_dict['name'], event_dict['quantity'],
                    self.quantity))

        if last_complete_event_name == list(status_map.values())[0]['name']:
            return last_complete_event_name

        return ', '.join(events)

    def is_shipping_event_permitted(self, event_type, quantity):
        """
        Test whether a shipping event with the given quantity is permitted

        This method should normally be overriden to ensure that the
        prerequisite shipping events have been passed for this line.
        """
        # Note, this calculation is simplistic - normally, you will also need
        # to check if previous shipping events have occurred.  Eg, you can't
        # return lines until they have been shipped.
        current_qty = self.shipping_event_quantity(event_type)
        return (current_qty + quantity) <= self.quantity

    def shipping_event_quantity(self, event_type):
        """
        Return the quantity of this line that has been involved in a shipping
        event of the passed type.
        """
        result = self.shipping_event_quantities.filter(
            event__event_type=event_type).aggregate(Sum('quantity'))
        if result['quantity__sum'] is None:
            return 0
        else:
            return result['quantity__sum']

    def has_shipping_event_occurred(self, event_type, quantity=None):
        """
        Test whether this line has passed a given shipping event
        """
        if not quantity:
            quantity = self.quantity
        return self.shipping_event_quantity(event_type) == quantity

    def get_event_quantity(self, event):
        """
        Fetches the ShippingEventQuantity instance for this line

        Exists as a separate method so it can be overridden to avoid
        the DB query that's caused by get().
        """
        return event.line_quantities.get(line=self)

    @property
    def shipping_event_breakdown(self):
        """
        Returns a dict of shipping events that this line has been through
        """
        status_map = OrderedDict()
        for event in self.shipping_events.all():
            event_type = event.event_type
            event_name = event_type.name
            event_quantity = self.get_event_quantity(event).quantity
            if event_name in status_map:
                status_map[event_name]['quantity'] += event_quantity
            else:
                status_map[event_name] = {
                    'event_type': event_type,
                    'name': event_name,
                    'quantity': event_quantity
                }
        return status_map

    # Payment event helpers

    def is_payment_event_permitted(self, event_type, quantity):
        """
        Test whether a payment event with the given quantity is permitted.

        Allow each payment event type to occur only once per quantity.
        """
        current_qty = self.payment_event_quantity(event_type)
        return (current_qty + quantity) <= self.quantity

    def payment_event_quantity(self, event_type):
        """
        Return the quantity of this line that has been involved in a payment
        event of the passed type.
        """
        result = self.payment_event_quantities.filter(
            event__event_type=event_type).aggregate(Sum('quantity'))
        if result['quantity__sum'] is None:
            return 0
        else:
            return result['quantity__sum']

    @property
    def is_product_deleted(self):
        return self.product is None

    def is_available_to_reorder(self, basket, strategy):
        """
        Test if this line can be re-ordered using the passed strategy and
        basket
        """
        if not self.product:
            return False, (_("'%(title)s' is no longer available") %
                           {'title': self.title})

        try:
            basket_line = basket.lines.get(product=self.product)
        except basket.lines.model.DoesNotExist:
            desired_qty = self.quantity
        else:
            desired_qty = basket_line.quantity + self.quantity

        result = strategy.fetch_for_product(self.product)
        is_available, reason = result.availability.is_purchase_permitted(
            quantity=desired_qty)
        if not is_available:
            return False, reason
        return True, None


class LineAttribute(models.Model):
    """
    An attribute of a line
    """
    line = models.ForeignKey(
        'Line',
        on_delete=models.CASCADE,
        related_name='attributes',
        verbose_name=_("Line"))
    option = models.ForeignKey(
        Option, null=True, on_delete=models.SET_NULL,
        related_name="line_attributes", verbose_name=_("Option"))
    type = models.CharField(_("Type"), max_length=128)
    value = models.CharField(_("Value"), max_length=255)

    class Meta:
        verbose_name = _("Line Attribute")
        verbose_name_plural = _("Line Attributes")

    def __str__(self):
        return "%s = %s" % (self.type, self.value)


class LinePrice(models.Model):
    """
    For tracking the prices paid for each unit within a line.

    This is necessary as offers can lead to units within a line
    having different prices.  For example, one product may be sold at
    50% off as it's part of an offer while the remainder are full price.
    """
    order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        related_name='line_prices',
        verbose_name=_("Option"))
    line = models.ForeignKey(
        'Line',
        on_delete=models.CASCADE,
        related_name='prices',
        verbose_name=_("Line"))
    quantity = models.PositiveIntegerField(_("Quantity"), default=1)
    price_incl_tax = models.DecimalField(
        _("Price (inc. tax)"), decimal_places=2, max_digits=12)
    price_excl_tax = models.DecimalField(
        _("Price (excl. tax)"), decimal_places=2, max_digits=12)
    shipping_incl_tax = models.DecimalField(
        _("Shiping (inc. tax)"), decimal_places=2, max_digits=12, default=0)
    shipping_excl_tax = models.DecimalField(
        _("Shipping (excl. tax)"), decimal_places=2, max_digits=12, default=0)

    class Meta:
        ordering = ('id',)
        verbose_name = _("Line Price")
        verbose_name_plural = _("Line Prices")

    def __str__(self):
        return _("Line '%(number)s' (quantity %(qty)d) price %(price)s") % {
            'number': self.line,
            'qty': self.quantity,
            'price': self.price_incl_tax}


# PAYMENT EVENTS


class PaymentEventType(models.Model):
    """
    Payment event types are things like 'Paid', 'Failed', 'Refunded'.

    These are effectively the transaction types.
    """
    name = models.CharField(_("Name"), max_length=128, unique=True)
    code = AutoSlugField(_("Code"), max_length=128, unique=True,
                         populate_from='name')

    class Meta:
        verbose_name = _("Payment Event Type")
        verbose_name_plural = _("Payment Event Types")
        ordering = ('name', )

    def __str__(self):
        return self.name


class PaymentEvent(models.Model):
    """
    A payment event for an order

    For example:

    * All lines have been paid for
    * 2 lines have been refunded
    """
    order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        related_name='payment_events',
        verbose_name=_("Order"))
    amount = models.DecimalField(
        _("Amount"), decimal_places=2, max_digits=12)
    # The reference should refer to the transaction ID of the payment gateway
    # that was used for this event.
    reference = models.CharField(
        _("Reference"), max_length=128, blank=True)
    lines = models.ManyToManyField(
        'Line', through='PaymentEventQuantity',
        verbose_name=_("Lines"))
    event_type = models.ForeignKey(
        'PaymentEventType',
        on_delete=models.CASCADE,
        verbose_name=_("Event Type"))
    # Allow payment events to be linked to shipping events.  Often a shipping
    # event will trigger a payment event and so we can use this FK to capture
    # the relationship.
    shipping_event = models.ForeignKey(
        'ShippingEvent',
        null=True,
        on_delete=models.CASCADE,
        related_name='payment_events')
    date_created = models.DateTimeField(_("Date created"), auto_now_add=True)

    class Meta:
        verbose_name = _("Payment Event")
        verbose_name_plural = _("Payment Events")
        ordering = ['-date_created']

    def __str__(self):
        return _("Payment event for order %s") % self.order

    def num_affected_lines(self):
        return self.lines.all().count()


class PaymentEventQuantity(models.Model):
    """
    A "through" model linking lines to payment events
    """
    event = models.ForeignKey(
        'PaymentEvent',
        on_delete=models.CASCADE,
        related_name='line_quantities',
        verbose_name=_("Event"))
    line = models.ForeignKey(
        'Line',
        on_delete=models.CASCADE,
        related_name="payment_event_quantities",
        verbose_name=_("Line"))
    quantity = models.PositiveIntegerField(_("Quantity"))

    class Meta:
        verbose_name = _("Payment Event Quantity")
        verbose_name_plural = _("Payment Event Quantities")
        unique_together = ('event', 'line')


# SHIPPING EVENTS


class ShippingEvent(models.Model):
    """
    An event is something which happens to a group of lines such as
    1 item being dispatched.
    """
    order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        related_name='shipping_events',
        verbose_name=_("Order"))
    lines = models.ManyToManyField(
        'Line', related_name='shipping_events',
        through='ShippingEventQuantity', verbose_name=_("Lines"))
    event_type = models.ForeignKey(
        'ShippingEventType',
        on_delete=models.CASCADE,
        verbose_name=_("Event Type"))
    notes = models.TextField(
        _("Event notes"), blank=True,
        help_text=_("This could be the dispatch reference, or a "
                    "tracking number"))
    date_created = models.DateTimeField(_("Date Created"), auto_now_add=True)

    class Meta:
        verbose_name = _("Shipping Event")
        verbose_name_plural = _("Shipping Events")
        ordering = ['-date_created']

    def __str__(self):
        return _("Order #%(number)s, type %(type)s") % {
            'number': self.order.number,
            'type': self.event_type}

    def num_affected_lines(self):
        return self.lines.count()


class ShippingEventQuantity(models.Model):
    """
    A "through" model linking lines to shipping events.

    This exists to track the quantity of a line that is involved in a
    particular shipping event.
    """
    event = models.ForeignKey(
        'ShippingEvent',
        on_delete=models.CASCADE,
        related_name='line_quantities',
        verbose_name=_("Event"))
    line = models.ForeignKey(
        'Line',
        on_delete=models.CASCADE,
        related_name="shipping_event_quantities",
        verbose_name=_("Line"))
    quantity = models.PositiveIntegerField(_("Quantity"))

    class Meta:
        verbose_name = _("Shipping Event Quantity")
        verbose_name_plural = _("Shipping Event Quantities")
        unique_together = ('event', 'line')

    def save(self, *args, **kwargs):
        # Default quantity to full quantity of line
        if not self.quantity:
            self.quantity = self.line.quantity
        # Ensure we don't violate quantities constraint
        if not self.line.is_shipping_event_permitted(
                self.event.event_type, self.quantity):
            raise exceptions.InvalidShippingEvent
        super().save(*args, **kwargs)

    def __str__(self):
        return _("%(product)s - quantity %(qty)d") % {
            'product': self.line.product,
            'qty': self.quantity}


class ShippingEventType(models.Model):
    """
    A type of shipping/fulfillment event

    Eg: 'Shipped', 'Cancelled', 'Returned'
    """
    # Name is the friendly description of an event
    name = models.CharField(_("Name"), max_length=255, unique=True)
    # Code is used in forms
    code = AutoSlugField(_("Code"), max_length=128, unique=True,
                         populate_from='name')

    class Meta:
        verbose_name = _("Shipping Event Type")
        verbose_name_plural = _("Shipping Event Types")
        ordering = ('name', )

    def __str__(self):
        return self.name


# DISCOUNTS


class OrderDiscount(models.Model):
    """
    A discount against an order.

    Normally only used for display purposes so an order can be listed with
    discounts displayed separately even though in reality, the discounts are
    applied at the line level.

    This has evolved to be a slightly misleading class name as this really
    track benefit applications which aren't necessarily discounts.
    """
    order = models.ForeignKey(
        'Order',
        on_delete=models.CASCADE,
        related_name="discounts",
        verbose_name=_("Order"))

    # We need to distinguish between basket discounts, shipping discounts and
    # 'deferred' discounts.
    BASKET, SHIPPING, DEFERRED = "Basket", "Shipping", "Deferred"
    CATEGORY_CHOICES = (
        (BASKET, _(BASKET)),
        (SHIPPING, _(SHIPPING)),
        (DEFERRED, _(DEFERRED)),
    )
    category = models.CharField(
        _("Discount category"), default=BASKET, max_length=64,
        choices=CATEGORY_CHOICES)

    offer_id = models.PositiveIntegerField(
        _("Offer ID"), blank=True, null=True)
    offer_name = models.CharField(
        _("Offer name"), max_length=128, db_index=True, blank=True)
    voucher_id = models.PositiveIntegerField(
        _("Voucher ID"), blank=True, null=True)
    voucher_code = models.CharField(
        _("Code"), max_length=128, db_index=True, blank=True)
    frequency = models.PositiveIntegerField(_("Frequency"), null=True)
    amount = models.DecimalField(
        _("Amount"), decimal_places=2, max_digits=12, default=0)

    # Post-order offer applications can return a message to indicate what
    # action was taken after the order was placed.
    message = models.TextField(blank=True)

    @property
    def is_basket_discount(self):
        return self.category == self.BASKET

    @property
    def is_shipping_discount(self):
        return self.category == self.SHIPPING

    @property
    def is_post_order_action(self):
        return self.category == self.DEFERRED

    class Meta:
        verbose_name = _("Order Discount")
        verbose_name_plural = _("Order Discounts")

    def save(self, **kwargs):
        if self.offer_id and not self.offer_name:
            offer = self.offer
            if offer:
                self.offer_name = offer.name

        if self.voucher_id and not self.voucher_code:
            voucher = self.voucher
            if voucher:
                self.voucher_code = voucher.code

        super().save(**kwargs)

    def __str__(self):
        return _("Discount of %(amount)r from order %(order)s") % {
            'amount': self.amount, 'order': self.order}

    # @property
    # def offer(self):
    #     Offer = get_model('offer', 'ConditionalOffer')
    #     try:
    #         return Offer.objects.get(id=self.offer_id)
    #     except Offer.DoesNotExist:
    #         return None
    #
    # @property
    # def voucher(self):
    #     Voucher = get_model('voucher', 'Voucher')
    #     try:
    #         return Voucher.objects.get(id=self.voucher_id)
    #     except Voucher.DoesNotExist:
    #         return None

    def description(self):
        if self.voucher_code:
            return self.voucher_code
        return self.offer_name or ""
