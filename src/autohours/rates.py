"""Compare and explicitly apply project settings through Clockify API v1."""

from decimal import Decimal
from urllib.parse import quote

from .models import UserError


def money(amount, currency):
    if amount is None:
        return "not set"
    return f"{Decimal(str(amount)) / 100:.2f} {currency or 'currency not set'}/h"


def billable(value):
    return "billable" if value is True else "not billable" if value is False else "not set"


def compare(destination, apply=False):
    destination.check()
    http = destination.http
    base = f"/workspaces/{destination.workspace}"
    workspace = http.request("GET", base)
    currency = (workspace.get("hourlyRate") or {}).get("currency")
    messages = []
    failed = False
    for project in destination.projects:
        agreement = project.agreement or {}
        if "billing" not in agreement:
            continue
        path = base + "/projects/" + quote(destination.project_ids[project.destination_project], safe="")
        current = http.request("GET", path)
        changed = current.get("billable") != project.billable
        if changed:
            messages.append(f"{project.name}: {billable(current.get('billable'))} -> {billable(project.billable)}")
        amount = None
        permitted = True
        if agreement["billing"] == "hourly":
            if "rate" not in agreement:
                messages.append(f"{project.name}: rate not set; rate unchanged.")
            elif "currency" not in agreement:
                messages.append(f"{project.name}: currency not set; rate unchanged.")
            elif currency != agreement["currency"]:
                messages.append(f"{project.name}: workspace currency {currency or 'unavailable'} differs from agreement {agreement['currency']}; refusing to apply rate.")
                permitted = False
                failed = failed or apply
            else:
                cents = Decimal(str(agreement["rate"])) * 100
                if cents != cents.to_integral_value() or cents > 2147483647:
                    raise UserError(f"{project.name}: Clockify rates require at most two decimal places and a 32-bit amount in cents.")
                amount = int(cents)
                rate = current.get("hourlyRate") or {}
                if rate.get("amount") != amount or rate.get("currency") != currency:
                    changed = True
                    messages.append(f"{project.name}: hourly rate {money(rate.get('amount'), rate.get('currency', currency))} -> {money(amount, currency)}")
        if not changed and permitted:
            rate_text = f", {money(amount, currency)}" if amount is not None else ""
            messages.append(f"{project.name}: in sync ({billable(project.billable)}{rate_text})")
        if not apply or not permitted or not changed:
            continue
        body = {key: current[key] for key in ("name", "color", "clientId", "archived", "note") if key in current}
        # API defaults isPublic to false, which fails for free workspaces.
        if "public" not in current:
            raise UserError(f"{project.name}: Clockify did not return project visibility; refusing an unsafe update.")
        body.update(isPublic=current["public"], billable=project.billable)
        if amount is not None:
            body.update(hourlyRate={"amount": amount, "includeApproved": False}, hourlyRateSet=True)
        http.request("PUT", path, body)
        effective = http.request("GET", path)
        rate = effective.get("hourlyRate") or {}
        good = effective.get("billable") == project.billable
        if amount is not None:
            good = good and rate.get("amount") == amount and rate.get("currency") == currency
        messages.append(f"{project.name}: {'confirmed' if good else 'MISMATCH after readback'}; {billable(effective.get('billable'))}, hourly rate={money(rate.get('amount'), rate.get('currency'))}.")
        failed = failed or not good
    return messages, failed
