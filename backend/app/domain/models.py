"""Canonical, solver-agnostic domain contracts for the PS1 data package."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
Priority = Annotated[int, Field(ge=1, le=3)]
BinaryFlag = Annotated[int, Field(ge=0, le=1)]


class RailModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Scenario(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class Bound(str, Enum):
    EASTBOUND = "EB"
    WESTBOUND = "WB"


class AccessType(str, Enum):
    PM = "PM"
    PC = "PC"
    C = "C"


class NatureOfWorks(str, Enum):
    LIVE = "Live"
    NON_LIVE_CONSIST = "Non-live (Consist)"
    NON_LIVE_OTHERS = "Non-live (Others)"


class LocationKind(str, Enum):
    TUNNEL_SECTOR = "tunnel sector"
    PLATFORM_SECTOR = "platform sector"


class LineRecord(RailModel):
    line_code: str
    line_name: str


class StationRecord(RailModel):
    station_id: str
    line_code: str
    seq: PositiveInt
    is_interchange: BinaryFlag


class SectorRecord(RailModel):
    sector_id: str
    line_code: str
    from_station_id: str
    to_station_id: str
    seq: PositiveInt
    is_shared: BinaryFlag


class LocationSupplyRecord(RailModel):
    location_id: str
    location_kind: LocationKind
    line_code: str
    bound: Bound
    supply_capacity: NonNegativeInt


class BufferLocationRecord(RailModel):
    nature_of_works: NatureOfWorks
    up_to_buffer_sectors: NonNegativeInt
    opposite_bound_required: BinaryFlag


class ParameterRecord(RailModel):
    key: str
    value: str


class ProjectRecord(RailModel):
    contract_number: str
    contract_description: str
    contract_award_date: date
    activity_type: str
    nature_of_activity: NatureOfWorks
    contract_priority: Priority
    contract_completion_date: date
    planned_completion_date: date
    number_of_workfronts: PositiveInt
    access_type: AccessType
    number_of_maximum_access_per_week: PositiveInt


class ActivityRecord(RailModel):
    activity_id: str
    contract_number: str
    activity_type: str
    start_location_id: str
    end_location_id: str
    total_accesses: PositiveInt
    planned_start_date: date
    predecessor_activity_id: str | None = None
    activity_priority: Priority

    @field_validator("predecessor_activity_id", mode="before")
    @classmethod
    def empty_predecessor_is_none(cls, value: object) -> object:
        return None if value == "" else value


class InstanceBundle(RailModel):
    """All eight official input tables in one canonical in-memory object."""

    lines: list[LineRecord]
    stations: list[StationRecord]
    sectors: list[SectorRecord]
    location_supply: list[LocationSupplyRecord]
    buffer_locations: list[BufferLocationRecord]
    parameters: list[ParameterRecord]
    projects: list[ProjectRecord]
    activities: list[ActivityRecord]


class AccessAssignment(RailModel):
    activity_id: str
    access_seq: PositiveInt
    week: PositiveInt
    eclo: BinaryFlag
    access_night: PositiveInt


class OccupancyAssignment(RailModel):
    activity_id: str
    week: PositiveInt
    location_id: str
    co_share_group: str


class ContractResult(RailModel):
    scenario: Scenario
    contract_number: str
    simulated_completion_date: date
    overrun_days: NonNegativeInt


class ScenarioSchedule(RailModel):
    """The only schedule shape downstream code should consume or export."""

    scenario: Scenario
    access_assignments: list[AccessAssignment]
    occupancy_assignments: list[OccupancyAssignment]
    contract_results: list[ContractResult]

    @model_validator(mode="after")
    def result_scenarios_match(self) -> "ScenarioSchedule":
        if any(result.scenario != self.scenario for result in self.contract_results):
            raise ValueError("every contract result must use the schedule scenario")
        return self
