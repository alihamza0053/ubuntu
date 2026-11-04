# HR API: Flutter integration brief

For the coding agent working in the Flutter app. Add three employee features to the existing app, using the existing login: attendance, salary and expense claims.

Each employee sees only their own data. The API enforces that on the server, so the app never chooses whose data to load.

## Status

| Item | State |
|---|---|
| API code | Written and tested with simulated data |
| API deployment | **Not deployed yet.** Keep the base URL in one constant |
| API token check | **Not connected to a login yet.** Calls return `503` until it is |
| Database columns | Checked against the real schema |

## Do this first: identify the login

Before writing feature code, read `pubspec.yaml` and the app's login code, then tell the project owner which case applies. The server's token check depends on the answer.

| You find | Meaning | Server work needed |
|---|---|---|
| `firebase_auth` | Firebase issues the token | Token check must change to verify Firebase tokens |
| `supabase_flutter` | Supabase issues the token | Token check must change to verify Supabase tokens |
| A custom login API that returns a JWT | Your backend issues the token | Must confirm the signing method and the fields it contains |
| A custom login API with no JWT, or a local-only login | No usable token exists | Server login work is needed first. **Stop and report this** |

Also report how a logged-in user maps to an employee code (`emp_code`), for example a token field, or an email that matches the HR record. Don't guess this mapping.

Build the feature screens against the API contract below, but don't describe the feature as finished until the owner confirms the server side is connected.

## Security rules

1. **Never send an employee ID to the API.** The server reads the employee from the verified token and ignores anything else.
2. **Never put a signing key, database password or API secret in the app.** Anything in a Flutter build can be extracted.
3. **Never create or sign a token in Flutter.** Only the login provider or login server does that.
4. **Never connect to PostgreSQL from the app.** All data goes through this API over HTTPS.
5. **Don't rely on hiding things in the UI for privacy.** The server enforces access.
6. Store tokens in secure storage (`flutter_secure_storage`, or the auth SDK's own storage), never in `SharedPreferences`.
7. Never log tokens, salaries or full API responses, including in `debugPrint` and crash reports.
8. On logout, clear the token and all cached HR data, so the next user of the device can't see it.

## API contract

**Base URL:** not assigned yet. Put it in one constant:

```dart
const apiBaseUrl = 'https://REPLACE-WITH-HR-API-DOMAIN';
```

**Every call except `/health` needs this header:**

```
Authorization: Bearer <token>
```

All calls are `GET`. All responses are JSON. Lists are newest first, and an empty list `[]` is a normal result.

### `GET /me`

Summary for the home or overview screen. Takes no parameters.

```json
{
  "employee_id": "32353",
  "attendance": [
    { "date": "2026-10-14", "check_in": "2026-10-14T08:58:00", "check_out": "2026-10-14T17:32:00" }
  ],
  "salary": [
    { "period_start": "2026-09-01", "period_end": "2026-09-30", "net_salary": 85000.5 }
  ],
  "claims": [
    { "voucher_no": "V-1", "date": "2026-10-02", "description": "Taxi", "amount": 4500.0 }
  ]
}
```

`attendance` and `claims` here cover about the last 31 days only. `salary` holds up to 36 periods.

### `GET /attendance?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

Returns the `attendance` list shown above. Up to 500 rows.

### `GET /claims?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD`

Returns the `claims` list shown above. Up to 500 rows.

For both date-range calls:

- Both dates are optional. `date_to` defaults to today, and `date_from` defaults to 31 days before `date_to`.
- The longest allowed range is 400 days.

### `GET /salary`

Returns the `salary` list shown above. Up to 36 periods. Takes no parameters.

### `GET /health`

No token needed. Returns `{"status": "ok"}`. Use it only to check that the API is reachable.

### Data details

- **Dates** (`date`, `period_start`, `period_end`) are `YYYY-MM-DD`.
- **`check_in` and `check_out`** have no time zone and are already local company time. Show them as they are, and don't apply `.toLocal()` or `.toUtc()`.
- **Any of `check_in`, `check_out`, `net_salary` or `amount` can be `null`.** A null `check_out` usually means it hasn't been recorded. Show a dash, never `0` or a crash.
- **Numbers:** parse with `num`, then `.toDouble()`. Don't cast directly to `double`.
- **Claims:** one voucher can have several lines, so `voucher_no` is not unique. Don't use it as a list key on its own. There is no status field, so don't show "approved" or "pending".
- **Salary range:** available from February 2026. The current month is deliberately left out until it is final, so show "No salary data" for gaps rather than an error.
- **Currency:** the API sends no currency. Use the format the app already uses.

### Errors

| Status | Meaning | What the app does |
|---|---|---|
| `400` | Bad date range | Show the `detail` message |
| `401` | Token missing, invalid or expired | Refresh the token if the SDK can, retry once, otherwise send the user to login |
| `404` | Wrong path | Treat as a bug |
| `422` | Badly formatted date | Fix the request. `detail` is a list here, not a string |
| `500` or `502` | Server problem | Show a retry message |
| `503` | Login not connected on the server yet | Show a retry message |

Errors normally look like `{"detail": "Log in again."}`. `detail` isn't always a string, and a `502` may return HTML instead of JSON, so parse errors defensively.

## Getting the token

Fetch the token immediately before each request, rather than holding one in a variable.

```dart
// Firebase: refreshes itself when close to expiry
final token = await FirebaseAuth.instance.currentUser?.getIdToken();

// Supabase: the SDK keeps the session refreshed
final token = Supabase.instance.client.auth.currentSession?.accessToken;

// Custom login API: read what the login call saved
final token = await const FlutterSecureStorage().read(key: 'auth_token');
```

A custom-login token must be a JWT signed by the server, with an `exp` expiry and the employee code in an `emp_code` field. If it isn't, report that to the owner rather than working around it.

## Suggested client

Follow the app's existing patterns for networking, state management and folder layout. Use this as a starting point, not a required structure.

```dart
import 'dart:convert';
import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.statusCode, this.message);
  final int statusCode;
  final String message;
  @override
  String toString() => message;
}

class HrApi {
  HrApi(this._getToken, {http.Client? client}) : _client = client ?? http.Client();

  final Future<String?> Function() _getToken;
  final http.Client _client;

  Future<dynamic> _get(String path, [Map<String, String>? query]) async {
    final token = await _getToken();
    if (token == null || token.isEmpty) {
      throw ApiException(401, 'Log in first.');
    }
    final uri = Uri.parse('$apiBaseUrl$path').replace(queryParameters: query);
    final response = await _client
        .get(uri, headers: {'Authorization': 'Bearer $token'})
        .timeout(const Duration(seconds: 20));
    if (response.statusCode == 200) {
      return jsonDecode(utf8.decode(response.bodyBytes));
    }
    var message = 'Something went wrong. Please try again.';
    try {
      final detail = jsonDecode(utf8.decode(response.bodyBytes))['detail'];
      if (detail is String) message = detail;
    } catch (_) {
      // Not JSON, for example a 502 page.
    }
    throw ApiException(response.statusCode, message);
  }

  Future<List<Attendance>> attendance({String? from, String? to}) async {
    final list = await _get('/attendance', _range(from, to)) as List;
    return list.map((e) => Attendance.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<Salary>> salary() async {
    final list = await _get('/salary') as List;
    return list.map((e) => Salary.fromJson(e as Map<String, dynamic>)).toList();
  }

  Future<List<Claim>> claims({String? from, String? to}) async {
    final list = await _get('/claims', _range(from, to)) as List;
    return list.map((e) => Claim.fromJson(e as Map<String, dynamic>)).toList();
  }

  Map<String, String>? _range(String? from, String? to) {
    final query = {
      if (from != null) 'date_from': from,
      if (to != null) 'date_to': to,
    };
    return query.isEmpty ? null : query;
  }
}

class Attendance {
  Attendance({required this.date, this.checkIn, this.checkOut});
  factory Attendance.fromJson(Map<String, dynamic> json) => Attendance(
        date: DateTime.parse(json['date'] as String),
        checkIn: DateTime.tryParse(json['check_in'] as String? ?? ''),
        checkOut: DateTime.tryParse(json['check_out'] as String? ?? ''),
      );
  final DateTime date;
  final DateTime? checkIn;
  final DateTime? checkOut;
}

class Salary {
  Salary({required this.periodStart, required this.periodEnd, this.netSalary});
  factory Salary.fromJson(Map<String, dynamic> json) => Salary(
        periodStart: DateTime.parse(json['period_start'] as String),
        periodEnd: DateTime.parse(json['period_end'] as String),
        netSalary: (json['net_salary'] as num?)?.toDouble(),
      );
  final DateTime periodStart;
  final DateTime periodEnd;
  final double? netSalary;
}

class Claim {
  Claim({required this.date, this.voucherNo, this.description, this.amount});
  factory Claim.fromJson(Map<String, dynamic> json) => Claim(
        date: DateTime.parse(json['date'] as String),
        voucherNo: json['voucher_no'] as String?,
        description: json['description'] as String?,
        amount: (json['amount'] as num?)?.toDouble(),
      );
  final DateTime date;
  final String? voucherNo;
  final String? description;
  final double? amount;
}
```

## Screens

| Screen | Content | Data source |
|---|---|---|
| Overview | Latest attendance, latest net salary, recent claims | `/me` |
| Attendance | Date, check in, check out, with a date range picker | `/attendance` |
| Salary | Pay period and net salary | `/salary` |
| Claims | Date, description, amount, voucher number, with a date range picker | `/claims` |

Every screen needs loading, empty, error-with-retry and pull-to-refresh states.

**Freshness:** load when a screen opens and on pull-to-refresh. If a screen must update by itself, poll attendance no faster than every 60 seconds, and only while that screen is visible. The data is only as new as the last HR system sync, so don't poll salary or claims.

**Platforms:** the API is set up for Android and iOS. It sends no CORS headers, so Flutter Web calls will be blocked by the browser.

## Done when

- [ ] The login type and the `emp_code` mapping have been reported to the owner.
- [ ] Nothing in the Dart code sends an employee ID to the API.
- [ ] No secrets are in the Dart code, assets or build configuration.
- [ ] The base URL exists in one place.
- [ ] Null `check_out`, `net_salary` and `amount` values display without errors.
- [ ] Claims with the same `voucher_no` all display.
- [ ] A `401` refreshes the token or returns to login, with no retry loop.
- [ ] Logout clears cached HR data.
- [ ] After deployment, two different employees log in and each sees only their own data.
