"""Planner tests with a fake Gemini client (no network). Scenario: Alex drives (needs a vehicle),
Maya and Jordan ride, all to Meijer on Saturday 13:45-14:30 local; the Tesla is the lowest-CO2 car."""
import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app import config, core, planner

SAT = datetime(2026, 10, 10, tzinfo=ZoneInfo("America/Detroit"))
MEIJER = (42.2405, -83.7660)


def local(h, m=0):
    return (SAT + timedelta(hours=h, minutes=m)).astimezone(timezone.utc)


START, END = local(13, 45), local(14, 30)


def make_ctx():
    def trip(id, user_id, role, lat, lng, **kw):
        return core.Trip(id=id, user_id=user_id, role=role, origin_lat=lat, origin_lng=lng, dest_name="Meijer",
                         dest_lat=MEIJER[0], dest_lng=MEIJER[1], window_start=START, window_end=END, **kw)

    def car(id, make_model, fuel, range_mi, eff, cents, lat, lng, avail=(12, 0)):
        return core.Vehicle(id=id, make_model=make_model, fuel_type=fuel, seats=5, range_mi=range_mi, efficiency=eff,
                            price_per_hour_cents=cents, lat=lat, lng=lng, avail_start=local(*avail), avail_end=local(17))

    trips = [trip(1, 2, "passenger", 42.2800, -83.7330),                      # Maya
             trip(2, 3, "passenger", 42.2720, -83.7500),                      # Jordan
             trip(3, 1, "driver", 42.2780, -83.7400, needs_vehicle=True)]     # Alex
    cars = [car(1, "Tesla Model 3", "ev", 270, 0.25, 800, 42.2820, -83.7260, avail=(13, 0)),
            car(2, "Honda Civic", "gas", 400, 33, 700, 42.2740, -83.7330),
            car(3, "Toyota RAV4", "gas", 450, 30, 1000, 42.2620, -83.7180),
            car(4, "Nissan Leaf", "ev", 150, 0.30, 900, 42.2650, -83.7500, avail=(13, 30))]
    return core.Ctx(trips={t.id: t for t in trips}, vehicles={v.id: v for v in cars})


def plan_json(depart=START, passengers=(1, 2), rationale=("same destination and overlapping windows",),
              vehicle_id=None, pickup_order=()):
    """Defaults leave vehicle and order empty, so code fills them (core.complete)."""
    return json.dumps({"groups": [{"driver_trip_id": 3, "passenger_trip_ids": list(passengers),
                                   "vehicle_id": vehicle_id, "pickup_order": list(pickup_order),
                                   "depart_time": planner._iso(depart), "rationale": list(rationale)}],
                       "unassigned": []})


def tool_call(name, **args):
    """A fake response asking for one function call."""
    fc = SimpleNamespace(name=name, args=args, id=None)
    return SimpleNamespace(function_calls=[fc], text=None, candidates=[SimpleNamespace(
        content={"role": "model", "parts": [{"function_call": {"name": name, "args": args}}]})])


class FakeClient:
    """Stands in for genai.Client: returns canned texts in order and records every call."""
    def __init__(self, *texts, delay=0.0):
        self.texts, self.delay, self.calls = list(texts), delay, []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append(SimpleNamespace(model=model, contents=list(contents), config=config))
        time.sleep(self.delay)
        out = self.texts.pop(0)
        return SimpleNamespace(text=out) if isinstance(out, str) else out


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")


def assert_tesla_plan(plan, ctx):
    assert core.validate(plan, ctx) == []
    [g] = plan.groups
    assert (g.driver_trip_id, sorted(g.passenger_trip_ids), g.vehicle_id) == (3, [1, 2], 1)   # Tesla (EV)
    assert sorted(g.pickup_order) == [1, 2]


def test_valid_first_try():
    ctx, fake = make_ctx(), FakeClient(plan_json())
    plan, opts, log = planner.draft(ctx, "test", mode="gemini", client=fake)
    assert_tesla_plan(plan, ctx)
    assert opts[3][0]["vehicle_id"] == 1 and opts[3][0]["fuel_type"] == "ev"
    assert set(log) == {"trigger", "planner", "tool_calls", "raw_output", "validator_errors",
                        "retries", "latency_ms", "fallback_used"}
    assert (log["planner"], log["retries"], log["fallback_used"], log["validator_errors"]) == ("gemini", 0, False, [[]])
    call = fake.calls[0]
    assert call.model == config.GEMINI_MODEL and call.config.response_mime_type == "application/json"
    sent = json.loads(call.contents[0]["parts"][0]["text"].split("\n", 1)[1])
    assert [t["id"] for t in sent["trips"]] == [1, 2, 3] and len(sent["vehicles"]) == 4


@pytest.mark.parametrize("bad, expect", [
    (plan_json(depart=START - timedelta(hours=4)), "outside trip"),   # {DEPART_BAD}
    (plan_json(passengers=(1,)), "trip 2 is missing"),
], ids=["depart_bad", "missing_trip"])
def test_invalid_then_corrected(bad, expect):
    ctx, fake = make_ctx(), FakeClient(bad, plan_json())
    plan, _, log = planner.draft(ctx, "test", mode="gemini", client=fake)
    assert_tesla_plan(plan, ctx)
    assert log["retries"] == 1 and not log["fallback_used"]
    assert any(expect in e for e in log["validator_errors"][0]) and log["validator_errors"][1] == []
    retry = fake.calls[1].contents                     # previous output + errors go back to Gemini
    assert retry[1]["role"] == "model" and expect in retry[2]["parts"][0]["text"]


def test_timeout_falls_back(monkeypatch):
    monkeypatch.setattr(config, "PLANNER_TIMEOUT_S", 0.2)
    ctx, fake = make_ctx(), FakeClient(plan_json(), delay=1.0)
    t = time.monotonic()
    plan, _, log = planner.draft(ctx, "test", mode="gemini", client=fake)
    assert time.monotonic() - t < 0.9
    assert log["fallback_used"] and log["tool_calls"][-1]["outcome"] == "timeout"
    assert_tesla_plan(plan, ctx)


def test_malformed_json_retries_then_falls_back():
    ctx = make_ctx()
    plan, _, log = planner.draft(ctx, "test", mode="gemini", client=FakeClient("not json", plan_json()))
    assert_tesla_plan(plan, ctx)
    assert log["retries"] == 1 and not log["fallback_used"] and "schema" in log["validator_errors"][0][0]

    fake = FakeClient(*["{oops"] * 3)
    plan, _, log = planner.draft(ctx, "test", mode="gemini", client=fake)
    assert_tesla_plan(plan, ctx)
    assert log["fallback_used"] and len(fake.calls) == 3 and len(log["validator_errors"]) == 3


def test_missing_key_or_deterministic_mode_never_calls_gemini(monkeypatch):
    ctx, fake = make_ctx(), FakeClient(plan_json())
    plan, _, log = planner.draft(ctx, "test", mode="deterministic", client=fake)
    assert_tesla_plan(plan, ctx)
    assert (log["planner"], log["fallback_used"]) == ("deterministic", False)

    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    plan, _, log = planner.draft(ctx, "test", mode="gemini", client=fake)
    assert_tesla_plan(plan, ctx)
    assert log["fallback_used"] and fake.calls == []


def test_rationale_with_digits_is_stripped():
    fake = FakeClient(plan_json(rationale=("same destination", "saves 3 miles", "an EV keeps CO2 low")))
    plan, _, log = planner.draft(make_ctx(), "test", mode="gemini", client=fake)
    assert plan.groups[0].rationale == ["same destination", "an EV keeps CO2 low"] and not log["fallback_used"]


FACTS = {"driver": "Alex", "passengers": ["Maya", "Jordan"], "vehicle": "Tesla Model 3 (EV)", "kg_co2_shared": 1.47,
         "alt_vehicle": "Honda Civic (gas)", "alt_kg_co2": 2.94, "cost_per_person_cents": 334,
         "miles_avoided": 12.3, "kg_co2_avoided": 5.2, "percent_reduction": 78.0}


def test_explain_rejects_numbers_not_in_facts(monkeypatch):
    monkeypatch.setattr(config, "EXPLAIN", "gemini")
    template = core.template_explanation(FACTS)
    good = ("Alex drives Maya and Jordan in the Tesla Model 3, about 1.5 kg CO2 versus 2.94 kg in the Civic. "
            "Each pays $3.34 and sharing cuts CO2 by 78%.")
    assert planner.explain(FACTS, client=FakeClient(good)) == good
    assert planner.explain(FACTS, client=FakeClient(good + " That is 40 fewer miles.")) == template

    monkeypatch.setattr(config, "EXPLAIN", "template")
    fake = FakeClient(good)
    assert planner.explain(FACTS, client=fake) == template and fake.calls == []


def test_thinking_level_is_sent():
    ctx, fake = make_ctx(), FakeClient(plan_json())
    planner.draft(ctx, "test", mode="gemini", client=fake)
    assert fake.calls[0].config.thinking_config.thinking_level.value == config.GEMINI_THINKING_LEVEL.upper()
    assert fake.calls[0].config.http_options.retry_options.attempts == 2      # the SDK never retries by default


def test_api_error_logs_http_code_not_message():
    class Unauthenticated(Exception):
        code, status = 401, "UNAUTHENTICATED"

    class Failing(FakeClient):
        def generate_content(self, model, contents, config):
            raise Unauthenticated("details that must not reach the log")

    plan, _, log = planner.draft(make_ctx(), "test", mode="gemini", client=Failing())
    assert log["fallback_used"] and log["tool_calls"][0]["outcome"] == "error: Unauthenticated 401 UNAUTHENTICATED"
    assert "details" not in json.dumps(log)
    assert_tesla_plan(plan, make_ctx())


def test_overloaded_model_switches_to_backup():
    class Overloaded(Exception):
        code, status = 503, "UNAVAILABLE"

    class Flaky(FakeClient):
        def generate_content(self, model, contents, config):
            if not self.calls:
                self.calls.append(SimpleNamespace(model=model))
                raise Overloaded()
            return super().generate_content(model, contents, config)

    ctx, fake = make_ctx(), Flaky(plan_json())
    plan, _, log = planner.draft(ctx, "test", mode="gemini", client=fake)
    assert [c.model for c in fake.calls] == [config.GEMINI_MODEL, config.GEMINI_BACKUP_MODEL]
    assert not log["fallback_used"] and log["tool_calls"][0]["outcome"] == "error: Overloaded 503 UNAVAILABLE"
    assert_tesla_plan(plan, ctx)


def test_no_driver_in_scope_skips_gemini():
    ctx, fake = make_ctx(), FakeClient()
    del ctx.trips[3]                                   # only Maya and Jordan: nobody can drive
    plan, _, log = planner.draft(ctx, "test", mode="gemini", client=fake)
    assert fake.calls == [] and log["planner"] == "deterministic" and not log["fallback_used"]
    assert plan.groups == [] and sorted(u.trip_id for u in plan.unassigned) == [1, 2]


def test_tools_answer_then_gemini_picks_vehicle_and_order():
    ctx = make_ctx()
    fake = FakeClient(tool_call("get_travel_matrix", trip_ids=[1, 2, 3]),
                      tool_call("list_available_vehicles", driver_trip_id=3, passenger_trip_ids=[1, 2],
                                depart_time=planner._iso(START)),
                      tool_call("validate_plan", groups=[{"driver_trip_id": 3, "passenger_trip_ids": [1, 2],
                                                          "vehicle_id": 2, "depart_time": planner._iso(START)}]),
                      tool_call("optimize_pickup_order", driver_trip_id=99, passenger_trip_ids=[]),
                      plan_json(vehicle_id=4, pickup_order=(1, 2)))      # Gemini picks the Leaf over the Tesla
    plan, opts, log = planner.draft(ctx, "test", mode="gemini", client=fake)
    [g] = plan.groups
    assert (g.vehicle_id, g.pickup_order) == (4, [1, 2]) and core.validate(plan, ctx) == []
    assert opts[3][0]["vehicle_id"] == 1                  # code still scores every vehicle for the reasons
    tools = [c for c in log["tool_calls"] if "tool" in c]
    assert [c["outcome"] for c in tools] == ["ok", "ok", "0 errors", "error"]   # trip 99 does not exist
    assert log["retries"] == 0 and not log["fallback_used"]
    sent = fake.calls[1].contents[-1]["parts"][0]["function_response"]["response"]
    assert sent["origin_mi"]["3"]["1"] > 0 and sent["destination_mi"]["1"]["2"] == 0
    vehicles = fake.calls[2].contents[-1]["parts"][0]["function_response"]["response"]["vehicles"]
    assert vehicles[0]["make_model"] == "Tesla Model 3" and vehicles[0]["feasible"]
    assert "tools" in fake.calls[0].config.model_dump(exclude_none=True)


def test_tool_rounds_are_capped(monkeypatch):
    monkeypatch.setattr(config, "PLANNER_MAX_TOOL_ROUNDS", 1)
    fake = FakeClient(tool_call("get_travel_matrix", trip_ids=[1]), plan_json())
    plan, _, log = planner.draft(make_ctx(), "test", mode="gemini", client=fake)
    assert fake.calls[0].config.tool_config is None
    assert fake.calls[1].config.tool_config.function_calling_config.mode.value == "NONE"
    assert_tesla_plan(plan, make_ctx())


def test_own_car_driver_never_books_a_vehicle():
    ctx = make_ctx()
    ctx.trips[3] = ctx.trips[3].model_copy(update={"needs_vehicle": False})
    plan, _, _ = planner.draft(ctx, "test", mode="gemini", client=FakeClient(plan_json(vehicle_id=1)))
    assert plan.groups[0].vehicle_id is None and core.validate(plan, ctx) == []
