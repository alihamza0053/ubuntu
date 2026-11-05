# HR API: Flutter integration brief

For the coding agent working in the MG Apparel employee app. Add three employee features, using the existing Firebase login: attendance, salary and expense claims.

Each employee sees only their own data. The API enforces that on the server, so the app never chooses whose data to load.

## Status

| Item | State |
|---|---|
| API code | Connected to Firebase Auth and tested with simulated data |
| API deployment | The new version must be on `https://maapi.mgdashboard.tech` before login works. Until then, calls return `503` |
| Real login | **Not tested yet** with a real employee account |
| Database columns | Checked against the real schema |

## Login: already decided

The app uses Firebase Auth on project `mg-apparel-app-yuze`, so no new login work is needed.

- Send the signed-in user's **Firebase ID token** to the API.
- The API verifies the token, then reads `employee_code` from that user's Firestore profile (`profiles/{uid}`). The app doesn't need to send it.
- An account with no `employee_code`, or a `status` other than `active`, gets `403`.

Don't add a new login screen, login API or custom token.

## This project

Follow what the app already does:

- **State:** Riverpod providers. **Routing:** go_router.
- **Packages:** add `http` to `pubspec.yaml`, as it isn't a dependency yet.
- **Demo mode:** repositories check `AppConfig.isDemoMode` and return sample data. Do the same, and never put real data in `demo_data.dart`.
- **Text:** the app is in English and Urdu. Add new strings to both `app_en.arb` and `app_ur.arb`.
- **Salary privacy:** the home screen hides salary by default through `SalaryVisibility` ("Rs ••••••"). Salary screens must respect the same setting.
- **Existing pay card:** `myPayProvider` reads HR-entered pay from Firestore `pay/{employee_code}`. Leave it as it is unless the owner asks to switch it to this API.

## Security rules

1. **Never send an employee ID to the API.** The server reads the employee from the verified token and ignores anything else.
2. **Never put a signing key, database password or API secret in the app.** Anything in a Flutter build can be extracted.
3. **Never create or sign a token in Flutter.** Only the login provider or login server does that.
4. **Never connect to PostgreSQL from the app.** All data goes through this API over HTTPS.
5. **Don't rely on hiding things in the UI for privacy.** The server enforces access.
6. Let the Firebase SDK hold the token. Don't save it yourself.
7. Never log tokens, salaries or full API responses, including in `debugPrint` and crash reports.
8. On logout, clear all cached HR data and Riverpod state, so the next user of the device can't see it.

## API contract

**Base URL:** put it in one constant, with no slash at the end. Every path below already starts with `/`, and a double slash returns `404`.

```dart
const apiBaseUrl = 'https://maapi.mgdashboard.tech';
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

No token needed. Returns `{"status": "ok", "database": "ok", "login": "ok"}`, or status `503` with `"error"` in the part that is down. Use it only to check that the API is reachable.

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
| `401` | Token missing, invalid or expired | Force a token refresh and retry once, then send the user to login |
| `403` | Account has no linked employee code, or isn't active | Show the `detail` message. Don't retry or log out |
| `404` | Wrong path | Treat as a bug |
| `422` | Badly formatted date | Fix the request. `detail` is a list here, not a string |
| `500` or `502` | Server problem | Show a retry message |
| `503` | The API can't check logins or reach its data right now | Show a retry message. Never log the user out on a `503` |

Errors normally look like `{"detail": "Log in again."}`. `detail` isn't always a string, and a `502` may return HTML instead of JSON, so parse errors defensively.

## Getting the token

Ask Firebase for the token immediately before each request, rather than holding one in a variable. The SDK refreshes it when it's close to expiry. Tokens last about an hour.

```dart
final hrApiProvider = Provider<HrApi>((ref) {
  return HrApi(({bool refresh = false}) async =>
      FirebaseService.currentUser?.getIdToken(refresh));
});
```

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

typedef TokenSource = Future<String?> Function({bool refresh});

class HrApi {
  HrApi(this._getToken, {http.Client? client}) : _client = client ?? http.Client();

  final TokenSource _getToken;
  final http.Client _client;

  Future<http.Response> _send(Uri uri, {bool refresh = false}) async {
    final token = await _getToken(refresh: refresh);
    if (token == null || token.isEmpty) {
      throw ApiException(401, 'Log in first.');
    }
    return _client
        .get(uri, headers: {'Authorization': 'Bearer $token'})
        .timeout(const Duration(seconds: 20));
  }

  Future<dynamic> _get(String path, [Map<String, String>? query]) async {
    final uri = Uri.parse('$apiBaseUrl$path').replace(queryParameters: query);
    var response = await _send(uri);
    if (response.statusCode == 401) {
      response = await _send(uri, refresh: true); // Retried once only.
    }
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

- [ ] The app uses the existing Firebase login, with no new login code.
- [ ] Nothing in the Dart code sends an employee ID to the API.
- [ ] No secrets are in the Dart code, assets or build configuration.
- [ ] The base URL exists in one place.
- [ ] Null `check_out`, `net_salary` and `amount` values display without errors.
- [ ] Claims with the same `voucher_no` all display.
- [ ] A `401` refreshes the token and retries once, with no retry loop.
- [ ] A `403` shows the "not linked" message.
- [ ] Salary respects the existing hide/show setting.
- [ ] New text exists in English and Urdu.
- [ ] Demo mode works with no network.
- [ ] Logout clears cached HR data.
- [ ] After deployment, two different employees log in and each sees only their own data.
