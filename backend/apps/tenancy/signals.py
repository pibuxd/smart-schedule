"""Many-to-many links must stay inside one company (e.g. an employee gets only positions of their company)."""

from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from apps.tenancy.base import is_company_owned


@receiver(m2m_changed, dispatch_uid="tenancy_same_company_m2m")
def reject_cross_company_links(sender, instance, action, reverse, model, pk_set, **kwargs):
    if action != "pre_add" or not pk_set:
        return
    if not (is_company_owned(type(instance)) and is_company_owned(model)):
        return
    if model._base_manager.filter(pk__in=pk_set).exclude(company_id=instance.company_id).exists():
        raise ValidationError("Nie można łączyć danych różnych firm.")
