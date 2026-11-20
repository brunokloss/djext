from django.conf import settings
from phonenumber_field.widgets import RegionalPhoneNumberWidget


class IntlTelInputWidget(RegionalPhoneNumberWidget):
    """One text input with a searchable country list and live formatting
    (intl-tel-input). Its script sends the number in E.164 on submit. The
    library is vendored in static/phone/vendor/, so nothing loads from a CDN."""

    def __init__(self, region=None, attrs=None):
        region = region or settings.PHONENUMBER_DEFAULT_REGION
        attrs = {
            "class": "intl-tel",
            "data-initial-country": region.lower(),
            **(attrs or {}),
        }
        super().__init__(region=region, attrs=attrs)

    class Media:
        css = {
            "all": (
                "phone/vendor/intl-tel-input/css/intlTelInput.min.css",
                "phone/css/phone_intl_tel.css",
            )
        }
        js = (
            "phone/vendor/intl-tel-input/js/intlTelInputWithUtils.min.js",
            "phone/js/phone_intl_tel.js",
        )
