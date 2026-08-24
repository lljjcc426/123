"""Deterministic regressions for cross-event patient scheduling constraints."""

from __future__ import annotations

import unittest

import pandas as pd

import run_unified_scheduler as scheduler
import verify_unified_schedule as verifier


START = pd.Timestamp("2024-01-01")


def capacity_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"weekday": weekday, "slot_index": slot, "capacity_main": 2}
            for weekday in range(7)
            for slot in range(96)
        ]
    )


def calendar() -> scheduler.WorkCalendar:
    return scheduler.WorkCalendar(
        START,
        START + pd.Timedelta(days=1),
        ["1", "2"],
        capacity_frame(),
        "capacity_main",
        {"1": 0.0, "2": 0.0},
        "lowest_id",
        10,
    )


def task(
    event_id: str,
    patient_id: str,
    room_id: str,
    duration_slots: int = 6,
    item_index: int = 1,
) -> scheduler.Task:
    return scheduler.Task(
        event_id=event_id,
        patient_id=patient_id,
        item_index=item_index,
        project_norm="test",
        category="test",
        duration_slots=duration_slots,
        compatible_rooms=(room_id,),
        capability_level="A",
        fasting=False,
        bladder=False,
        bedside=False,
        bladder_ready_dt=START,
    )


class PatientConstraintRegression(unittest.TestCase):
    def test_cross_event_transfer_after_prior_event(self) -> None:
        work = calendar()
        first = scheduler.plan_event(
            work,
            [task("E1", "P1", "1")],
            START + pd.Timedelta(hours=9),
            START + pd.Timedelta(hours=11),
        )
        second = scheduler.plan_event(
            work,
            [task("E2", "P1", "2")],
            START + pd.Timedelta(hours=9),
            START + pd.Timedelta(hours=11),
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(work.times[second[0].start_index], START + pd.Timedelta(hours=9, minutes=40))

    def test_future_event_enforces_transfer_in_reverse_direction(self) -> None:
        work = calendar()
        blocker = scheduler.plan_event(
            work,
            [task("BLOCK", "OTHER", "2")],
            START + pd.Timedelta(hours=9),
            START + pd.Timedelta(hours=10),
        )
        future = scheduler.plan_event(
            work,
            [task("E3", "P2", "1")],
            START + pd.Timedelta(hours=10),
            START + pd.Timedelta(hours=11),
        )
        earlier = scheduler.plan_event(
            work,
            [task("E4", "P2", "2")],
            START + pd.Timedelta(hours=9),
            START + pd.Timedelta(hours=10),
        )
        self.assertIsNotNone(blocker)
        self.assertIsNotNone(future)
        self.assertIsNone(earlier)

    def test_failed_event_rolls_back_patient_intervals(self) -> None:
        work = calendar()
        failed = scheduler.plan_event(
            work,
            [
                task("E5", "P3", "1", item_index=1),
                task("E5", "P3", "1", item_index=2),
            ],
            START + pd.Timedelta(hours=8),
            START + pd.Timedelta(hours=8, minutes=45),
        )
        self.assertIsNone(failed)
        self.assertNotIn("P3", work.patient_intervals)
        self.assertFalse(work.room_busy.any())
        self.assertEqual(int(work.doctor_load.sum()), 0)

    def test_independent_verifier_detects_transfer_shortfall(self) -> None:
        schedule = pd.DataFrame(
            [
                {
                    "patient_id": "P4", "event_id": "E6", "sequence_position": 1,
                    "room_id": "1", "start_dt": START + pd.Timedelta(hours=9),
                    "end_dt": START + pd.Timedelta(hours=9, minutes=30),
                },
                {
                    "patient_id": "P4", "event_id": "E7", "sequence_position": 1,
                    "room_id": "2", "start_dt": START + pd.Timedelta(hours=9, minutes=35),
                    "end_dt": START + pd.Timedelta(hours=10),
                },
            ]
        )
        self.assertEqual(verifier.patient_timeline_violations(schedule, 10), (0, 1))


if __name__ == "__main__":
    unittest.main()
