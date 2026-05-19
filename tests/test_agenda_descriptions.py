import pandas as pd

from agenda_descriptions import (
    AGENDA_DESCRIPTION_COLUMN,
    AGENDA_ITEM_COLUMN,
    annotate_sessions_with_agenda_descriptions,
    build_agenda_description_pairs,
    strip_derived_description_fields,
)


def test_build_agenda_description_pairs_deduplicates_rows():
    df = pd.DataFrame(
        [
            {AGENDA_ITEM_COLUMN: "10", AGENDA_DESCRIPTION_COLUMN: "Rel-20 Study of 6GR"},
            {AGENDA_ITEM_COLUMN: "10", AGENDA_DESCRIPTION_COLUMN: "Rel-20 Study of 6GR"},
            {AGENDA_ITEM_COLUMN: "10.5.4", AGENDA_DESCRIPTION_COLUMN: "Scheduling"},
        ]
    )

    assert build_agenda_description_pairs(df) == [
        {"agenda_item": "10", "description": "Rel-20 Study of 6GR"},
        {"agenda_item": "10.5.4", "description": "Scheduling"},
    ]


def test_annotate_falls_back_from_x_to_parent():
    sessions = [
        {
            "room_name": "RAN1_main",
            "name": "10.5.4.x",
            "duration_minutes": 30,
            "specified_start_time": None,
            "chair": None,
            "group_header": "6G",
            "agenda_item": None,
        }
    ]

    annotated = annotate_sessions_with_agenda_descriptions(
        sessions,
        {
            "10": "Rel-20 Study of 6GR",
            "10.5.4": "Downlink control channel, scheduling and HARQ operation",
        },
    )

    assert annotated[0]["description"] == (
        "Downlink control channel, scheduling and HARQ operation"
    )
    assert annotated[0]["agenda_descriptions"][0]["matched_agenda_item"] == "10.5.4"
    assert annotated[0]["agenda_descriptions"][0]["hierarchy"] == [
        {
            "agenda_item": "10",
            "description": "Rel-20 Study of 6GR",
            "has_description": True,
        },
        {
            "agenda_item": "10.5",
            "description": None,
            "has_description": False,
        },
        {
            "agenda_item": "10.5.4",
            "description": "Downlink control channel, scheduling and HARQ operation",
            "has_description": True,
        },
    ]


def test_strip_derived_description_fields():
    assert strip_derived_description_fields(
        [
            {
                "name": "10.5.4.x",
                "description": "generated",
                "agenda_descriptions": [],
            }
        ]
    ) == [{"name": "10.5.4.x"}]
