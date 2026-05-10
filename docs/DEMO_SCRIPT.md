# ThirdEye — Demo Video Script

**Target length:** ~2:00 (spoken + live phone rings + AI voice playback).
**Speakers:** 4 (A, B, C, D). Speaker D runs the live demo on stage.
**Pace:** passionate, direct. Hit numbers hard. No filler.

---

## [0:00 – 0:18] — SPEAKER A (HOOK)

> Last year, **a hundred and four million packages** were stolen in America. **Thirty-seven billion dollars, gone.** Only **twelve percent** of those thefts ever lead to an arrest.
>
> And more than **seventy percent of American homes** don't have a single security camera. Why? Because Ring costs **two hundred dollars upfront and twenty bucks a month, forever.** Safety became a subscription.

**~55 words**

---

## [0:18 – 0:40] — SPEAKER B (PROBLEM)

> The thirty percent who *did* pay — they paid for surveillance. Ring streams your front porch to Amazon's servers. They have **twenty-one hundred police partnerships**, and they just teamed up with **Flock — the camera network ICE uses.**
>
> And every camera flat-alerts. Delivery driver, stray cat, break-in, elder fall — same buzz. A thief hitting five porches in a row looks like five disconnected events. Nobody sees the pattern.

**~62 words**

---

## [0:40 – 1:06] — SPEAKER C (ARCHITECTURE — works with any camera, runs on edge, data stays private)

> ThirdEye is the third path. **Any camera works.** Your iPhone. An old Android sitting in a drawer. A ten-year-old webcam. Even the Ring you already bought. **Anything that streams video, plugs in. No new hardware, ever.**
>
> Your laptop is the brain. A **nine-billion-parameter vision model runs locally** — on your machine, not in the cloud. Every frame stays on your device. Every inference happens at the edge. Four tiers — **ambient, notice, alert, emergency** — classified in real time, thirty frames a second.
>
> **The cloud never sees a pixel.** Your neighbors get a two-hundred-byte signed event blob. Never a frame. Never a clip. **Your data stays yours.**

**~95 words**

---

## [1:06 – 1:40] — SPEAKER D (LIVE DEMO)

> Watch.

*[Teammate walks up, drops package, leaves]*

> Delivery. **AMBIENT.** System stays quiet.

*[Hooded teammate grabs the package]*

> Theft. **ALERT.**

*[Judge's phone rings — Twilio call — judge answers — AI voice plays:]*

> *"This is your ThirdEye agent. Six seconds ago, someone in a red hoodie removed a package from your porch and walked north. Press one to alert your neighbors."*

*[Judge presses 1. MMS clip lands. Dashboard flashes mesh broadcast]*

> Eight-second clip on the judge's phone. Four neighbors just got the same alert. **No human dispatcher. No cloud round-trip. The classification happened on this laptop.**
>
> Now — emergency. Elder fall.

*[Three phones ring simultaneously. AI voice on the 911-dispatcher phone:]*

> *"This is ThirdEye automated dispatch. Fall detected at twelve thirty-four Maple Street. Resident not moving for thirty seconds. EMS recommended."*

> **Three phones, two seconds. Signed clip locked for evidence.**

**~80 words spoken + ~30 words of AI voice playback**

---

## [1:40 – 2:00] — SPEAKER A (CLOSE)

> Same software, three missions. **Theft.** Falls — **fourteen million Americans** over sixty-five fall every year. An hour on the floor doubles six-month mortality.
>
> **Wildfire smoke.** Davis is fire country. AI cameras detect fires **forty-five minutes** before the first 911 call.
>
> ThirdEye is open source. **Any camera. Any laptop. Every frame stays on your device.** No hardware. No subscription. No surveillance.
>
> **Security stops being something you buy. It becomes software you download.**
>
> Vote ThirdEye.

**~75 words**

---

## Stage choreography notes

- **Pre-cache the AI audio** for both ALERT and EMERGENCY scenarios. Twilio failover = instant.
- **Speaker D** holds the demo phone at chest height during ALERT — the ringing should be audible to the camera mic.
- **Three "cascade" phones** lined up in front during EMERGENCY. They MUST all ring within 2 seconds of each other. Test 3x before recording.
- **Backup**: Hour-12 backup video already exists. If a live component fails, splice that clip in.

## Numbers to drill (no slip-ups)

- 104 million packages / $37 billion / 12% arrest rate
- 70% of homes have no camera / $20 a month for Ring
- 2,100 police partnerships / Ring × Flock × ICE
- **9 billion parameters running locally / 30 fps / 4 tiers / cloud sees nothing**
- 14 million elder falls per year / 45-minute wildfire detection lead

## Privacy / edge talking points (work into ad-libs if needed)

- "The 9-billion-parameter model is on **this laptop**." (point at it)
- "Your video never touches the internet."
- "When your neighbor gets an alert, they don't see your footage — they see a 200-byte signed message."
- "We don't have a server. There is nothing for us to leak."

## Pacing rehearsal

| Speaker | Beat | Words | Spoken time @ ~170 wpm |
|---|---|---|---|
| A | Hook | 55 | ~19s |
| B | Problem | 62 | ~22s |
| C | Architecture | 95 | ~33s |
| D | Live demo | 80 + 30 (AI) | ~38s |
| A | Close | 75 | ~26s |
| **Total** | | **~367 spoken + 30 AI** | **~138s = 2:18** |

If you run long (likely closer to 2:15 with stage transitions), trim in this order:
1. **Speaker B**: drop the Flock/ICE clause (saves ~5s)
2. **Speaker C**: drop "Even the Ring you already bought" (saves ~3s)
3. **Close**: drop "An hour on the floor doubles six-month mortality" (saves ~4s)

If you run short, expand the Ring × ICE story in B or add the **fifty-eight percent lifetime victimization** stat to the hook.
