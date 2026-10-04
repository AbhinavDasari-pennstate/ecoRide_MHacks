# eCARide live demo

Everything needed to run the phone demo on stage. Commands assume macOS or Linux and a
`backend/.venv`. No credential ever appears in this file.

## 1. Bring it up

```sh
backend/scripts/start_demo.sh
```

That starts the backend on 8000, starts ngrok on the reserved domain
`reprint-purveyor-foil.ngrok-free.dev` (so the public URL never changes), re-registers the
voice agent, resets the demo data and logins, starts the frontend on 5173, and finishes with
preflight. It is safe to run twice: anything already listening is reused.

To reset between runs without restarting anything:

```sh
cd backend && .venv/bin/python scripts/demo_state.py
```

To check readiness at any time, without changing anything:

```sh
cd backend && .venv/bin/python scripts/preflight.py
```

Preflight ends with `READY TO CALL` or a list of what to fix. To walk the whole flow end to
end without touching the phone:

```sh
cd backend && .venv/bin/python scripts/verify_demo.py
```

## 2. Logins

Sign in at <http://localhost:5173/login>. The same table is written to
`backend/DEMO_LOGINS.local.txt` every time the demo data is reset, and that file is
gitignored. These are demo passwords. Do not reuse them anywhere.

| Person | User | Role | Email | Password | On stage |
| --- | --- | --- | --- | --- | --- |
| Alex | 1 | rider | alex@eride.demo | demo-alex-2026 | the caller; this is the +1 925-967-7432 account |
| Maya | 2 | rider | maya@eride.demo | demo-maya-2026 | already waiting, accepts |
| Jordan | 3 | rider | jordan@eride.demo | demo-jordan-2026 | already waiting, accepts |
| Sam | 4 | owner | sam@eride.demo | demo-sam-2026 | owns the Tesla, approves the booking |
| Dana | 8 | buyer | buyer@eride.demo | demo-buyer-2026 | the data portal, optional |

Put Alex on the main screen at **My trips** (`/profile`). It polls every 5 seconds, so the
phone booking appears on its own with no refresh. Maya, Jordan and Sam can be on other
screens on the same page.

## 3. The call

Dial **+1 628-277-9064** from **+1 925-967-7432**.

Eco answers with "Hi Alex, this is Eco from eCARide. Do you want to book a ride, or check on
one?" because the initiation webhook recognised the number before the call connected.

What to say:

1. "I want to drive to Meijer on Saturday around 2."
2. If asked whether you need a car: "Yes, I need to borrow one."
3. Eco says one short line, books once, then reads the match: Sam's Tesla Model 3, the price
   each, and the kilograms of CO2 saved.
4. "Yes please" when it offers to text the details. It will only ever send that once.

While you are still on the call, Alex's **My trips** screen shows the trip, the group, the
Tesla, the fare and the CO2 figure. Then on the other screens: Maya accepts, Jordan accepts,
Alex accepts, and Sam approves the car. The match flips to **confirmed**.

Numbers on this machine for the seeded scenario: the Tesla at about **$4.23 each** and about
**7.7 kg of CO2 avoided**, roughly **86 percent** less than everyone driving separately. The
Tesla wins on CO2 even though Priya's Civic is closer to Alex and cheaper, which is the point
worth saying out loud.

## 3b. The data portal, and the booking that feeds it

Sign in as **buyer@eride.demo** on another screen and open **Data Portal**. Sections 01 to 03 are
the simulated dataset as before: 6 drivers, 48 trips, one shared car, with the Simulated data badge
on it throughout.

Section **04 / Models** is new. Three models were fitted offline on that dataset with
scikit-learn at a fixed seed, and their parameters are committed, so the running API scores without
scikit-learn installed.

| Model | What it does | Honest metric |
| --- | --- | --- |
| IsolationForest | flags trips that sit furthest from the rest | 8 of 48 flagged. Unsupervised, so there is no accuracy to quote. A flag means unusual, not unsafe. |
| Gradient boosting | chance a trip contains a Review severity event, from miles, duration, speed, energy rate and start hour, with every event count withheld | cross validated ROC AUC **0.7285**, against a logistic baseline of **0.5566** |
| Linear regression | kWh per mile from driving features | held out MAE **0.003386** kWh per mile, R2 **0.9291** |

Things worth saying out loud, because the panel says them too:

- The banner reads "Models trained on simulated data, not validated". Every card has a "how this is
  computed" note.
- The driver ranking is D5 75, D3 74, D4 50, and D1, D2 and D6 at 0. That matches the data: only
  D3, D4 and D5 ever have Review events. A logistic model was tried first and put D6 top with 48,
  which was wrong, and the note on the card says so and why.
- The R2 of 0.93 on energy looks great and the caveat under it explains that this dataset's energy
  follows a fixed formula, so the regression recovered a formula rather than predicting a real car.
- There is a CSV of per trip features and scores next to the original JSON download.

**The booking feeds the portal.** When the ride you booked by phone reaches confirmed, one
simulated telemetry trip is generated for it. Its distance is the planned route, so it corresponds
to the real booking; the duration, energy and driving events are generated from a seed taken from
the match id, so the same ride always produces the same trip. It is tagged **live booking** in the
flagged list, and the portal shows "Trips from live bookings: 1". The driver is an anonymous code
such as BK-8418, with no name, number or address anywhere on it.

On Sam's **My cars** page, **Data earnings (demo numbers)** shows $0.85 for that one confirmed ride,
with a line saying no money moves. On the rider card, the fare is unchanged and the card says the
data programme pays the car owner, not the rider.

Cancelling the driver's trip marks the generated trip voided rather than deleting it, so it leaves
the portal and the models but is still counted.

To prove the whole chain without touching the phone:

```sh
cd backend && .venv/bin/python scripts/verify_demo.py
```

That books through the public MCP endpoint, confirms with all three riders and the owner, and
asserts the telemetry, the scoring, Sam's earning and that a reset clears it. 37 checks.

To regenerate the models (needs requirements-dev.txt, which has scikit-learn, numpy and joblib):

```sh
cd backend && .venv/bin/python scripts/train_buyer_models.py
```

That rewrites `fixtures/buyer_models.json`, which is committed, and
`backend/models/anomaly_isolation_forest.joblib`, which is not. The run asserts that the pure
Python scorer reproduces scikit-learn to 1e-9 on every trip before it writes anything.

## 4. What is on and what is off

| Setting | Value for the demo | Why |
| --- | --- | --- |
| `VOICE_PLANNER` | `deterministic` | the booking answers in about 0.01 s. Gemini takes 5 to 9 s and up to 20 s, which is a long silence on a call. Set it to `gemini` if you would rather show Gemini planning live. |
| `PLANNER` | `deterministic` | set it to `gemini` to show Gemini on the web flow and in `/agent-runs` while keeping the call fast |
| `NOTIFY_ON_MATCH` | currently **on** in `.env` | each real change texts every traveller and the car owner once. The ship default is `off`. Set it back to `off` if you do not want live texts attempted. Note that the Twilio trial is at its daily cap, see section 5. |
| `SMTP_*` | not set | confirmation emails are appended to `backend/outbox.local.log` instead of being sent |
| `MAPS_SERVER_KEY` | not set | distances are straight line estimates, and the app says so. The voice agent can only book places it knows by name, which for this demo means Meijer. See section 7. |
| `DEMO_DATA_PAYOUT_CENTS` | 85 | what an owner is shown as earning per confirmed ride. Demo numbers, no payment is processed. |

## 5. Troubleshooting

| What you see | What it means | Fix |
| --- | --- | --- |
| Twilio says "application error" when you call | the tunnel is down, or the backend behind it is | `backend/scripts/start_demo.sh`, then check `ngrok is running` and `the tunnel reaches the backend` in preflight |
| The call connects then drops immediately | the initiation webhook failed or returned an incomplete set of variables. A missing variable ends the call at once. | preflight's `every dynamic variable comes back` check; look at `backend/.local-logs/backend.log` |
| Eco answers but does not know who you are | the caller's number does not match a seeded user | confirm `DEMO_PHONES=Alex=+19259677432` in `backend/.env`, then rerun `demo_state.py` |
| Eco introduces itself twice | the live agent prompt is stale | preflight's `the agent prompt is the current one`; rerun `setup_voice.py` |
| Eco books the trip twice | should not happen now: a repeat returns the existing trip and says "That is already booked" | check for two trips in Alex's dashboard and tell us |
| Eco goes quiet for several seconds | `VOICE_PLANNER` is set to `gemini` | set `VOICE_PLANNER=deterministic` and restart the backend |
| The booking works but the web app shows nothing | signed in as the wrong person, or the data was reset after the call | Alex must be signed in as alex@eride.demo, and `demo_state.py` clears trips |
| "Trip is posted, no match yet" | the waiting passengers are missing, so there is no group to form | run `demo_state.py` |
| Nothing is texted | `NOTIFY_ON_MATCH` is off by default, and a Twilio trial can only text numbers verified in the console | the notice still appears in Notifications on the profile page |
| A text arrives with no details in it | `TWILIO_SMS_TEMPLATE` is set, so Twilio only sends a template id | clear it, or use the in-app Notifications list |
| No text arrives at all, error 63038 in the Twilio log | the trial account is at its daily message cap. Checked on 2026-10-04: 234 messages in the log, none delivered, 184 of them 63038, 36 unverified numbers (21608) and 14 A2P unregistered (30034) | nothing to fix in the code. Show the Notifications list on the profile page instead, which carries the same details. The cap resets daily; upgrading the Twilio account removes it |
| The buyer portal shows no 04 / Models section | the insights request failed or the account is not a buyer | sign in as buyer@eride.demo, and check "the buyer insights endpoint answers" in preflight |
| The portal shows a leftover BK- trip from an earlier run | demo data was not reset | run `demo_state.py`, which clears generated trips and payouts |
| ngrok URL changed | the reserved domain was not used | `start_demo.sh` passes `--url`, so always start it that way; otherwise set `PUBLIC_URL` and rerun `setup_voice.py` |
| After a laptop restart | nothing is running | `backend/scripts/start_demo.sh` brings all of it back, and the reserved domain means ElevenLabs needs no changes |

## 6. If you want real texts or emails

Both are off. To turn texts on, set `NOTIFY_ON_MATCH=on` in `backend/.env` and restart the
backend. On a Twilio trial only numbers verified in the Twilio console can receive them.

To turn email on, set all five of `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` and
`EMAIL_FROM`. For Gmail:

1. Go to <https://myaccount.google.com/security> and turn on two step verification. App
   passwords are not offered without it.
2. Go to <https://myaccount.google.com/apppasswords>.
3. Name it something like "ecaride demo" and create it. Google shows a 16 character password
   once, in four groups of four.
4. In `backend/.env` set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
   `SMTP_USER=your.address@gmail.com`, `SMTP_PASSWORD` to those 16 characters with the spaces
   removed, and `EMAIL_FROM` to the same address.
5. Restart the backend. Confirmation emails then go out instead of to the outbox file.

Keep the app password in `backend/.env` only. It is gitignored, and it is not your Google
account password. You can revoke it from the same page at any time.

## 7. Road routing, if you want it

`MAPS_SERVER_KEY` is present in `backend/.env` but empty, so this is off. Everything works without
it: distances are straight line miles times 1.3, the map draws straight segments, and the app says
"Route distances are estimated" on the trip card. The one real limit is that the voice agent can
only book a destination it recognises by name, and `KNOWN_PLACES` in `backend/app/config.py` holds
only Meijer. Saying "Meijer" or "the Meijer on Ann Arbor-Saline" works. Saying "the grocery store"
returns an error.

To turn real road routing on:

1. Go to <https://console.cloud.google.com/projectcreate> and create a project, or pick an existing
   one. Billing has to be enabled on it; Routes and Geocoding are not available on a project without
   a billing account, though both have a free monthly allowance that a demo will not exceed.
2. Enable the two APIs, one at a time:
   - <https://console.cloud.google.com/apis/library/routes.googleapis.com> and press Enable.
   - <https://console.cloud.google.com/apis/library/geocoding-backend.googleapis.com> and press Enable.
3. Go to <https://console.cloud.google.com/apis/credentials>, press Create credentials, then API key.
   Copy it once.
4. Still on that page, open the new key and restrict it. Under API restrictions choose Restrict key
   and tick only Routes API and Geocoding API. Leave application restrictions as None, because this
   key is used server side from the backend. Do not reuse this key in the frontend: the browser map
   needs its own key with the Maps JavaScript API and an HTTP referrer restriction.
5. Put it in `backend/.env` as `MAPS_SERVER_KEY=` followed by the key, with no quotes.
6. Restart the backend so it loads, then reseed so the route cache warms up:

   ```sh
   cd backend && .venv/bin/python scripts/demo_state.py
   ```

7. Check it took effect:

   ```sh
   curl -s http://127.0.0.1:8000/health      # expect "maps":"live"
   .venv/bin/python scripts/verify_demo.py   # expect the same 37 checks to pass
   ```

What changes once it is live: every distance becomes Google road miles rather than straight line
times 1.3, so the fare, the kilograms of CO2 and the detour figures all move; the match carries a
real road polyline instead of straight segments; `impact.assumptions.distance_source` flips from
`estimate` to `google_routes` and the trip card stops saying distances are estimated; the pickup
order may be replaced by Google's optimised order when that does not break a validator rule; and the
voice agent can book any address it can geocode rather than only Meijer. The expected direction is
that road miles are a little longer than the 1.3 multiplier guesses on short campus hops, so the
fare and the CO2 both tick up slightly, but the Tesla should still win on CO2. Rerun
`verify_demo.py` and read the numbers it prints rather than trusting that.

If a key is wrong or the APIs are not enabled, nothing breaks: the first failed call turns the
network off for that planning run and logs a warning with the key scrubbed, and the run finishes on
estimates. A phone booking cannot fail because of it.
