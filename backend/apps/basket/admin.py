from django.contrib import admin

from .models import Line, Basket, LineAttribute


class LineInline(admin.TabularInline):
    model = Line
    readonly_fields = ('line_reference', 'product', 'price_excl_tax',
                       'price_incl_tax', 'price_currency')


class LineAdmin(admin.ModelAdmin):
    list_display = ('id', 'basket', 'product', 'quantity',
                    'price_excl_tax', 'price_currency', 'date_created')
    readonly_fields = ('basket', 'line_reference', 'product',
                       'price_currency', 'price_incl_tax', 'price_excl_tax',
                       'quantity')


class BasketAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'status', 'num_lines',
                    'date_created', 'date_submitted',
                    'time_before_submit')
    readonly_fields = ('owner', 'date_merged', 'date_submitted')
    inlines = [LineInline]


admin.site.register(Basket, BasketAdmin)
admin.site.register(Line, LineAdmin)
admin.site.register(LineAttribute)
