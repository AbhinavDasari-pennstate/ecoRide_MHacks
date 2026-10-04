# ERIDE live demo

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

Eco answers with "Hi Alex, this is Eco from ecoRide. Do you want to book a ride, or check on
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

## 4. What is on and what is off

| Setting | Value for the demo | Why |
| --- | --- | --- |
| `VOICE_PLANNER` | `deterministic` | the booking answers in about 0.01 s. Gemini takes 5 to 9 s and up to 20 s, which is a long silence on a call. Set it to `gemini` if you would rather show Gemini planning live. |
| `PLANNER` | `deterministic` | set it to `gemini` to show Gemini on the web flow and in `/agent-runs` while keeping the call fast |
| `NOTIFY_ON_MATCH` | `off` | turning it on texts every traveller and the car owner once per real change. Leave it off unless you mean to send real texts. |
| `SMTP_*` | not set | confirmation emails are appended to `backend/outbox.local.log` instead of being sent |
| `MAPS_SERVER_KEY` | not set | distances are straight line estimates, and the app says so. The voice agent can only book places it knows by name, which for this demo means Meijer. |

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
3. Name it something like "eride demo" and create it. Google shows a 16 character password
   once, in four groups of four.
4. In `backend/.env` set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
   `SMTP_USER=your.address@gmail.com`, `SMTP_PASSWORD` to those 16 characters with the spaces
   removed, and `EMAIL_FROM` to the same address.
5. Restart the backend. Confirmation emails then go out instead of to the outbox file.

Keep the app password in `backend/.env` only. It is gitignored, and it is not your Google
account password. You can revoke it from the same page at any time.
