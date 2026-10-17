"""Compare and explicitly apply project settings through Clockify API v1."""

from decimal import Decimal
from urllib.parse import quote

from .models import UserError


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
        messages.append(f"{project.name}: billable {current.get('billable')} -> {project.billable}")
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
                messages.append(f"{project.name}: hourly rate {rate.get('amount', 'not set')} cents {rate.get('currency', currency)} -> {amount} cents {currency}")
        if not apply or not permitted:
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
        messages.append(f"{project.name}: {'confirmed' if good else 'MISMATCH after readback'}; billable={effective.get('billable')}, hourly rate={rate.get('amount', 'not set')} cents {rate.get('currency', 'not set')}.")
        failed = failed or not good
    return messages, failed
