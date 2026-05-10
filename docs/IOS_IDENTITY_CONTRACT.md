# iOS ↔ web identity handoff contract

The web app (`apps/web`) now expects to be signed in with a 6-character
code minted by the iPhone during onboarding. This doc spells out the
exact backend contract so the iOS agent can wire the phone side.

Backend lives in `action_router/identity.py` + `action_router/service.py`.
All endpoints exist on the same `BackendConfig.defaultURL` the iOS app
already uses.

## Flow

```
┌────────────┐                    ┌────────────────┐                    ┌────────────┐
│  iPhone    │                    │ Action router  │                    │   Web UI   │
│ (Xcode app)│                    │   :8001        │                    │  :3100     │
└─────┬──────┘                    └───────┬────────┘                    └─────┬──────┘
      │                                   │                                   │
      │ 1. user enters name + email       │                                   │
      │                                   │                                   │
      │  POST /api/identity               │                                   │
      │  { name, email, device_id }       │                                   │
      │ ────────────────────────────────▶│                                   │
      │                                   │                                   │
      │ ◀──── 201  { code: "AJQ2NH",      │                                   │
      │              session_id, … }      │                                   │
      │                                   │                                   │
      │ 2. show "AJQ2NH" on screen        │                                   │
      │                                   │                                   │
      │                                   │   3. user opens /login, types it  │
      │                                   │                                   │
      │                                   │      POST /api/identity/by-code/  │
      │                                   │           AJQ2NH/claim            │
      │                                   │ ◀──────────────────────────────── │
      │                                   │                                   │
      │                                   │      200  { status: "claimed" … } │
      │                                   │ ─────────────────────────────────▶│
      │                                   │                                   │
      │ 4. (optional) phone polls         │                                   │
      │    /api/identity/by-code/AJQ2NH   │                                   │
      │    until status == "claimed",     │                                   │
      │    then dismiss the code screen   │                                   │
      │                                   │                                   │
      │ 5. (parallel) phone polls         │                                   │
      │    /api/warmup until ready        │                                   │
      │    so onboarding shows progress   │                                   │
```

## Endpoints

### `POST /api/identity`

iPhone calls this once after the user submits the name/email screen.

Request:

```jsonc
{
  "name":  "Aditya Singh",
  "email": "adisin650@gmail.com",
  "device_id": "iPhone-Aditya"   // optional; helpful for the audit log
}
```

Response (`201 Created`):

```jsonc
{
  "session_id": "f6856ee7e2d747a294684588acffdf1c",
  "code":       "AJQ2NH",
  "name":       "Aditya Singh",
  "email":      "adisin650@gmail.com",
  "device_id":  "iPhone-Aditya",
  "status":     "pending",
  "created_at": 1778431171.77,
  "claimed_at": null
}
```

The phone shows `code` on screen. Codes are 6-char alphanumeric, case-
insensitive, ambiguous chars (`O`, `0`, `I`, `1`, `L`) excluded.

### `GET /api/identity/by-code/{code}`

Either side can poll this. Returns the same shape as above with
`status: "pending"` until the web claims it, then `status: "claimed"`
with a non-null `claimed_at`. Returns `404` for unknown / expired codes.

Codes auto-expire 10 minutes after the last activity (poll or claim).

### `POST /api/identity/by-code/{code}/claim`

The web side calls this when the user types the code. iOS shouldn't call
it — it's the "vouched" step. Returns the full session with
`status: "claimed"`. Returns `404` if the code is wrong/expired.

### `GET /api/warmup`

Truthful "are the models ready" signal. The vision engine only flips
its registry entry to `running` after `_prewarm()` finishes loading
YOLO + Qwen + processor caches — so when we report `ready` here, the
first real frame doesn't pay a cold-start tax.

Response:

```jsonc
{
  "state":     "cold" | "warming" | "ready",
  "elapsed_s": 12.3,    // time spent warming, or warmup duration if ready
  "running":   1,
  "warming":   0,
  "crashed":   0,
  "nodes":     [/* CameraEntry array, same shape as /api/cameras */]
}
```

While the user is on the name/email screen, the iPhone should poll
`/api/warmup` every 2 seconds; flip the on-phone progress UI to "ready"
when `state == "ready"`. By the time the user lands on the web app the
models should already be hot, so first inference latency drops
substantially.

`POST /api/warmup` returns the same payload — useful as a single
"start polling" hit if the iOS side prefers a write+read pattern over
two GETs.

## Suggested iOS implementation sketch

```swift
struct Identity: Codable {
    let session_id: String
    let code: String
    let name: String
    let email: String
    let status: String
    let claimed_at: Double?
}

func submitIdentity(name: String, email: String) async -> Identity? {
    var req = URLRequest(url: URL(string: "\(API.backendURL)/api/identity")!)
    req.httpMethod = "POST"
    req.setValue("application/json", forHTTPHeaderField: "Content-Type")
    req.httpBody = try? JSONSerialization.data(withJSONObject: [
        "name": name, "email": email, "device_id": UIDevice.current.identifierForVendor?.uuidString ?? ""
    ])
    let (data, _) = try await URLSession.shared.data(for: req)
    return try? JSONDecoder().decode(Identity.self, from: data)
}

// Poll until web claims, then transition out of the code screen.
func pollClaim(code: String) async -> Bool {
    let url = URL(string: "\(API.backendURL)/api/identity/by-code/\(code)")!
    while !Task.isCancelled {
        if let (data, _) = try? await URLSession.shared.data(from: url),
           let id = try? JSONDecoder().decode(Identity.self, from: data),
           id.status == "claimed" {
            return true
        }
        try? await Task.sleep(nanoseconds: 1_500_000_000)
    }
    return false
}
```

## Test it without iOS

```bash
# 1. boot the backend
make run    # or: make backend

# 2. simulate the phone
RESP=$(curl -s -X POST http://127.0.0.1:8001/api/identity \
  -H 'Content-Type: application/json' \
  -d '{"name":"Aditya","email":"adisin650@gmail.com","device_id":"sim"}')
echo "$RESP"           # note the "code" field, e.g. "AJQ2NH"

# 3. open http://localhost:3100/login and type that code →
#    web should say "Logged in as Aditya"

# 4. verify the warmup signal (after vision pipeline loads ~30s):
watch -n 2 'curl -s http://127.0.0.1:8001/api/warmup | jq .state'
# state goes  cold → warming → ready
```
