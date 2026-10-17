# Clockify integration

Requests use the global Clockify API v1 base `https://api.clockify.me/api/v1` and the environment-only `CLOCKIFY_API_KEY`. No real account is used in tests. See the [official v1 API reference](https://docs.clockify.me/).

## Endpoints

| Method and path | Purpose |
| --- | --- |
| `GET /user` | Resolve the signed-in user |
| `GET /workspaces` | Resolve the workspace by name or ID |
| `GET /workspaces/{workspaceId}` | Read workspace `hourlyRate.currency` |
| `GET /workspaces/{workspaceId}/projects` | Resolve configured projects, with pagination |
| `GET /workspaces/{workspaceId}/projects/{projectId}` | Read billable status and hourly rate before and after updates |
| `PUT /workspaces/{workspaceId}/projects/{projectId}` | Update `billable` and the project's `hourlyRate` |
| `GET /workspaces/{workspaceId}/user/{userId}/time-entries` | Check overlaps and monthly logged time, with pagination |
| `POST /workspaces/{workspaceId}/time-entries` | Write approved entries |

The current v1 reference exposes project hourly rates through the project update endpoint: `hourlyRateSet = true` and `hourlyRate = {"amount": 12550, "includeApproved": false}` for a fictional rate of 125.50. It does not list a separate `/projects/{projectId}/hourly-rate` endpoint. The `/projects/{projectId}/users/{userId}/hourly-rate` endpoint changes a project member's rate, which is a different setting and is not used.

Amounts are sent as integer cents. Rates with more than two decimal places or outside the API's signed 32-bit range are refused instead of rounded. Currency must be explicitly agreed and match the workspace currency. No workspace currency is changed. No retroactive `since` date is supplied, and approved rates are not explicitly updated.

Project updates preserve the returned name, color, client, archive state, note and visibility. The API uses `isPublic` in requests and `public` in responses. This matters on the free plan, where setting a project private is not supported. Missing visibility stops an update. After a write, autohours reads the project again and checks billable status, rate amount and currency. A mismatch exits unsuccessfully; inspect Clockify and rerun the diff before trying again. A partially completed request is not rolled back automatically.

Readback confirms project settings only. Task or project-member overrides can change what Clockify charges for individual entries. Review those separately in Clockify. Flat and retainer agreements do not set an hourly rate. `rates` never changes time entries or creates invoices.

Overlap checks include earlier entries and running timers. Cap accounting includes all of the signed-in user's project entries for the calendar month, clipped at month boundaries, regardless of billable status. Running timers reserve time through the month end. Other users' entries are outside this personal timesheet tool's cap scope. Do not use it as a shared team budget lock or run concurrent writers.
