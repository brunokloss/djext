from django.db.models import Q
from post_office.models import Email


def delete_emails_to(address: str) -> None:
    """The emails sent to `address` (to, cc or bcc), kept for
    EMAIL_RETENTION_DAYS with their body. Each one, with its logs."""
    address = address.lower()
    found = Email.objects.filter(
        Q(to__icontains=address) | Q(cc__icontains=address) | Q(bcc__icontains=address)
    ).only("to", "cc", "bcc")
    # icontains also finds bob.ana@...: only the exact address counts.
    ids = [
        email.pk
        for email in found
        if address in {a.lower() for a in (*email.to, *email.cc, *email.bcc)}
    ]
    Email.objects.filter(pk__in=ids).delete()
