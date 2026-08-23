# HOMEOSTASIS — what is defended, and what is only declared

Written 23 August 2026, at the end of the command that built the survival layer.
Every sensor claim below was **executed on this machine** and its real output is
quoted. Nothing here is inferred from documentation.

The point of the file: the next command should start from facts rather than from
a report, and should be able to tell a variable that is *defended* from one that
is merely *watched* from one that is *not readable at all*.

---

## Why only two are built

The review that specified this layer ranked five defended variables and warned
against building all five actuators at once:

> the disk cleanup causes a CPU spike, which raises a thermal alarm, which
> throttles, which slows the cycle, which raises a duration alarm — that is not
> homeostasis, that is an autoimmune disorder.

So RAM and disk are built, in that order, and the other three are declared and
left alone. The restraint is the design, not a shortfall.

---

## BUILT — the two defended variables

Thresholds live in `config/homeostasis.json`, human-approved and sha256-stamped
(`8242a23a3ed8e2f8…`). A mismatch is a hard refusal, never a silent default.

| variable | unit | notice | action | gate | hysteresis |
|---|---|---|---|---|---|
| `ram_free` | MB | 1200 | 900 | 600 | 300 |
| `disk_free_pct` | % | 28 | 15 | 5 | 5 |

Each level has a **distinct mechanical effect**:

- **notice** — recorded, nothing else.
- **action** — an actuator fires. Disk has one (`core/disk_actuator.py`); RAM
  does not, and that is stated below rather than implied.
- **gate** — `core/survival_gate.py` refuses to start the cycle, writes
  `CYCLE_REFUSED_SURVIVAL_GATE` to the existence ledger with variable, value,
  threshold and time-to-threshold, and fires the siren at ALARM level.

Sensors, both readable, both used:

```
ram_free       psutil.virtual_memory().available / 1024**2
disk_free_pct  shutil.disk_usage(BASE) -> 100 * free / total
```

### The gap inside the built pair

**`ram_free` has no actuator.** Its `action` level currently has the same effect
as `notice` — it is recorded and nothing happens — which is exactly the failure
this layer was built to avoid, and it is only tolerable because the `gate` level
above it is real. Freeing RAM would mean killing or deferring work inside a
running cycle, which needs a defer queue that does not exist yet. Until then the
honest description is: RAM is *gated*, not *defended*.

---

## NOT BUILT — the other three

### 3. CPU temperature

**Sensor: NOT READABLE on this machine today.** Three routes were tried:

```
psutil 7.2.2
  psutil.sensors_temperatures        -> ATTRIBUTE DOES NOT EXIST on this platform
  Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature
                                     -> rc=1, "Access denied"  (PermissionDenied)
  Get-CimInstance -ClassName Win32_TemperatureProbe
                                     -> rc=0, empty  (class present, no instances)
```

`psutil.sensors_temperatures` is a Linux/macOS-only attribute; it is absent, not
failing. The WMI thermal zone exists but needs an elevated process. The CIM
temperature-probe class returns no instances, which is normal on consumer
hardware.

What *is* readable, and is not the same thing:

```
psutil.cpu_percent(interval=1)  -> 3.4
psutil.cpu_freq()               -> scpufreq(current=2555.0, min=0.0, max=3201.0)
```

Sustained frequency well below `max` under load is a *proxy* for thermal
throttling — it is the effect, observed after the fact, not the temperature.

**Existing actuator: none, and none is needed yet.** No code in this repo
throttles, sleeps, or reduces concurrency in response to load. `core/step_budget.py`
bounds a step by *time*, not by heat.

**Before it can be wired, one of these must be true:**
1. the cycle runs elevated, or a helper service does, so `root/wmi` answers — a
   privilege change that is a decision for a human, not for the system; or
2. LibreHardwareMonitor / OpenHardwareMonitor is installed and its named pipe or
   WMI namespace is read — a third-party dependency and a driver; or
3. the variable is redefined as **sustained frequency deficit** rather than
   temperature, which needs no privileges at all and is measurable today.

Option 3 is the cheap one and it is honest, provided it is named for what it
measures. It should not be called "temperature".

### 4. Network availability

**Sensor: READABLE.** Measured just now:

```
8.8.8.8        port 53    OK    50 ms
api.groq.com   port 443   OK    53 ms
localhost      port 11434 OK  2045 ms      <- the local Ollama, and see below
psutil.net_if_stats()  Wi-Fi up, speed=866
```

A `socket.create_connection` with a short timeout is enough; no HTTP request and
no API key is required to answer "is there a network".

One measurement worth keeping: **the local Ollama port took 2.0 seconds to
accept a TCP connection.** A remote TLS endpoint answered in 53 ms. That is not
a network problem, and it is a number to re-measure before anyone concludes the
local fallback is "fast because it is local".

**Existing actuators: three, and they are good ones.**

- `core/backend_policy.py` — classifies failures instead of retrying blindly.
  402/Payment Required disables a provider for the whole process; 429/rate limit
  is a cooldown; three consecutive all-cloud failures inside one step stop cloud
  attempts for the rest of that step.
- `core/backend_policy.py` `SELF_DIRECTED` — `phase_debrief`, `brain_stance`,
  `autopsy`, `step_prediction` never touch the cloud, so the calls the system
  needs most when the network is gone are the ones that do not need it.
- `core/llm_backend.py:call_ollama_fallback` and `core/cortex_llm_resource.py`
  — the local model as the last tier.

**Before it can be wired:** the actuators exist but they are *reactive* — they
fire after a call has already failed and charged its latency to a step's
ceiling. Making network a defended variable means deciding, at the step
boundary, to go local *before* spending the timeout. What has to be true first
is a cheap pre-flight whose own cost is smaller than the failure it avoids, and
the 2045 ms local-port measurement above says the naive version of that check is
not obviously cheap. Measure before building.

### 5. Cloud quota

**Sensor: PARTIALLY READABLE — inferred, never queried.** There is no call in
this repo that asks a provider "how much quota is left". What exists is a
running count of observed outcomes:

```
core/step_budget.py   cloud_state()   -> {"cloud_empty": n, "demoted": bool,
                                          "limit": CLOUD_EMPTY_LIMIT}
                      cloud_demoted() -> bool
```

Quota exhaustion is therefore known only *after* it has been hit, by counting
EMPTY tiers. Groq and the other providers do return quota headers on a real
request; nothing here reads them.

**Existing actuator: yes, and it already behaves like one.**
`core/step_budget.py` stops giving the cloud the first slice after three EMPTY
tiers in one cycle, and `fast_cycle_runner.main()` clears that demotion at boot
because a rate-limit window closes overnight — a deliberate refusal to let a
within-cycle observation harden into a policy nobody set.

**Before it can be wired:** read the rate-limit headers that come back on calls
the system is already making (`x-ratelimit-remaining-*` on Groq), so the count
becomes a measurement instead of an inference. That is a change inside
`core/groq_backend.py` and costs nothing extra — the response is already in
hand. Until then a "quota" threshold would be a threshold on a guess.

---

## Summary

| # | variable | sensor today | actuator today | status |
|---|---|---|---|---|
| 1 | `ram_free` | readable | **none** | gated, not defended |
| 2 | `disk_free_pct` | readable | `core/disk_actuator.py` | **defended** |
| 3 | CPU temperature | **not readable** (needs elevation or a driver) | none | declared |
| 4 | network | readable | reactive, in `backend_policy` | declared |
| 5 | cloud quota | inferred only | `step_budget` demotion | declared |

## The commands that show the state without starting a cycle

```
venv/Scripts/python.exe core/survival_gate.py            # both variables, full
venv/Scripts/python.exe core/p_survive.py                # the scalar
venv/Scripts/python.exe core/disk_actuator.py --level action   # dry run
venv/Scripts/python.exe core/unclean_stop.py             # was the last stop clean
```

`p_survive_next_cycle` is a metric for a human reading a trend line. It never
enters a model prompt, the survival gate does not consult it, and
`test/test_p_survive.py` holds that by assembling every prompt component in the
repo and searching the text.
