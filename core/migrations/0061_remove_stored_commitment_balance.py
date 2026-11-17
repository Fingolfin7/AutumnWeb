from django.db import migrations
from django.utils import timezone


def derived_balance(commitment, Period, Adjustment, alias, now):
    """Read the historical ledger without depending on application code."""
    if commitment.ledger_start_at is None:
        # Uninitialized commitments start at zero, with no ledger to replay.
        return 0
    latest = (
        Period.objects.using(alias)
        .filter(
            commitment_id=commitment.pk,
            generation=commitment.generation,
            period_end__lte=now,
        )
        .order_by("-period_end", "-pk")
        .first()
    )
    running = latest.balance_out if latest is not None else 0
    bounds = {
        "effective_at__gt" if latest is not None else "effective_at__gte": (
            latest.period_end if latest is not None else commitment.ledger_start_at
        ),
        "effective_at__lte": now,
    }
    for adjustment in (
        Adjustment.objects.using(alias)
        .filter(commitment_id=commitment.pk, **bounds)
        .order_by("effective_at", "seq")
    ):
        if adjustment.kind in {"opening", "restart_carry"}:
            running = adjustment.amount
        else:
            running += adjustment.amount
    return running


def check_balances(apps, schema_editor):
    Commitment = apps.get_model("core", "Commitment")
    Period = apps.get_model("core", "CommitmentPeriod")
    Adjustment = apps.get_model("core", "CommitmentAdjustment")
    alias = schema_editor.connection.alias
    now = timezone.now()
    mismatches = []
    # Check inactive and dirty commitments too: this reads the last persisted
    # replay, without reconciling sessions or creating new period rows.
    for commitment in Commitment.objects.using(alias).all().iterator():
        derived = derived_balance(commitment, Period, Adjustment, alias, now)
        if derived != commitment.balance:
            mismatches.append(
                f"id={commitment.pk}: stored={commitment.balance}, derived={derived}"
            )
    if mismatches:
        raise RuntimeError("Commitment balance mismatch: " + "; ".join(mismatches))


def backfill_balances(apps, schema_editor):
    Commitment = apps.get_model("core", "Commitment")
    Period = apps.get_model("core", "CommitmentPeriod")
    Adjustment = apps.get_model("core", "CommitmentAdjustment")
    alias = schema_editor.connection.alias
    now = timezone.now()
    for commitment in Commitment.objects.using(alias).all().iterator():
        balance = derived_balance(commitment, Period, Adjustment, alias, now)
        Commitment.objects.using(alias).filter(pk=commitment.pk).update(balance=balance)


class Migration(migrations.Migration):
    dependencies = [("core", "0060_project_subproject_versions")]

    operations = [
        migrations.RunPython(check_balances, backfill_balances),
        migrations.RemoveField(model_name="commitment", name="balance"),
        migrations.RemoveField(model_name="commitment", name="last_reconciled"),
    ]
