"""The rules a new location starts with."""

from apps.rules.models import RuleSetting
from engine.rules_catalog import RULES


def add_good_practice_rules(location) -> None:
    """A new location outside a group starts with the good-practice rules switched on, in catalog order (a location
    in a group follows the group's rules instead). Call inside the transaction that saves the location."""
    good = [rule for rule in RULES if rule.good_practice]
    RuleSetting.objects.for_company(location.company_id).bulk_create(
        RuleSetting(
            company_id=location.company_id,
            location=location,
            rule_code=rule.code,
            position=place,
            is_hard=rule.default_hard,
        )
        for place, rule in enumerate(good, start=1)
    )
