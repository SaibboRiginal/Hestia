"""Built-in exercise library (seeded once, ids stable everywhere: uuid5 of the slug).

Each entry: slug, English name (shown translated), primary muscles, secondary muscles, equipment, kind,
movement pattern, stressed joints (pain rule), unilateral. The names people write for each exercise, in every
language, are ``hercules.exercise.<slug>`` in ``locales/<lang>/words.json`` (aliases, for matching). The user's own exercises live next to these
(``is_custom``) and seeded ones can be edited or archived like any other.
"""
from __future__ import annotations

import uuid

from hestia_common.i18n import words

NAMESPACE = uuid.UUID("6f1c2a43-0b7e-4d0a-9f55-4f3c8e9a1b20")

MUSCLES = {
    "chest": "Chest", "front_delts": "Front delt", "side_delts": "Side delt",
    "rear_delts": "Rear delt", "triceps": "Triceps", "biceps": "Biceps", "forearms": "Forearms",
    "lats": "Lats", "upper_back": "Upper back", "traps": "Traps", "lower_back": "Lower back",
    "abs": "Abs", "obliques": "Obliques", "glutes": "Glutes", "quads": "Quads",
    "hamstrings": "Hamstrings", "adductors": "Adductors", "abductors": "Abductors", "calves": "Calves",
    "neck": "Neck",
}
# Coarse groups for weekly volume and goals ("back 2/week").
MUSCLE_GROUPS = {
    "chest": ["chest"], "shoulders": ["front_delts", "side_delts", "rear_delts"],
    "arms": ["biceps", "triceps", "forearms"], "back": ["lats", "upper_back", "traps", "lower_back"],
    "core": ["abs", "obliques"], "legs": ["quads", "hamstrings", "glutes", "adductors", "abductors", "calves"],
}
JOINTS = {"shoulder": "Shoulder", "elbow": "Elbow", "wrist": "Wrist", "lower_back": "alt::Lower back",
          "hip": "Hip", "knee": "Knee", "ankle": "Ankle", "neck": "Neck"}
EQUIPMENT = {"barbell": "Barbell", "dumbbell": "Dumbbells", "machine": "Machine", "cable": "Cables",
             "kettlebell": "Kettlebell", "band": "Elastic band", "bodyweight": "Bodyweight", "smith": "Smith machine",
             "ez_bar": "EZ bar", "trap_bar": "Trap bar", "other": "Other"}
KINDS = {"weight_reps": "Weight × reps", "bodyweight_reps": "Bodyweight",
         "weighted_bodyweight": "Weighted bodyweight", "assisted_bodyweight": "Assisted bodyweight",
         "reps_only": "Reps only", "duration": "Duration", "distance_duration": "Distance and duration",
         "weight_duration": "Weight × duration"}
PATTERNS = {"squat": "Squat", "hinge": "Hip hinge", "push_h": "Horizontal push", "push_v": "Vertical push",
            "pull_h": "Horizontal pull", "pull_v": "Vertical pull", "lunge": "Lunge", "carry": "Transport",
            "core": "Core", "isolation": "Isolation"}

# slug, name, primary, secondary, equipment, kind, pattern, joints, unilateral
_E = [
    # ── chest ──
    ("bench_press", "Barbell bench press", ["chest"], ["front_delts", "triceps"], "barbell", "weight_reps", "push_h", ["shoulder", "elbow", "wrist"], False),
    ("incline_bench_press", "Barbell incline bench press", ["chest", "front_delts"], ["triceps"], "barbell", "weight_reps", "push_h", ["shoulder", "elbow", "wrist"], False),
    ("decline_bench_press", "Barbell decline bench press", ["chest"], ["triceps", "front_delts"], "barbell", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("close_grip_bench_press", "Close-grip bench press", ["triceps", "chest"], ["front_delts"], "barbell", "weight_reps", "push_h", ["elbow", "wrist", "shoulder"], False),
    ("db_bench_press", "Dumbbell bench press", ["chest"], ["front_delts", "triceps"], "dumbbell", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("db_incline_press", "Incline dumbbell press", ["chest", "front_delts"], ["triceps"], "dumbbell", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("db_fly", "Dumbbell fly", ["chest"], ["front_delts"], "dumbbell", "weight_reps", "isolation", ["shoulder"], False),
    ("cable_fly", "Cable fly", ["chest"], ["front_delts"], "cable", "weight_reps", "isolation", ["shoulder"], False),
    ("pec_deck", "Pectoral machine", ["chest"], [], "machine", "weight_reps", "isolation", ["shoulder"], False),
    ("chest_press_machine", "Chest press", ["chest"], ["triceps", "front_delts"], "machine", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("smith_bench_press", "Smith machine bench press", ["chest"], ["triceps", "front_delts"], "smith", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("push_up", "Push-up", ["chest"], ["triceps", "front_delts", "abs"], "bodyweight", "bodyweight_reps", "push_h", ["shoulder", "wrist", "elbow"], False),
    ("weighted_push_up", "Weighted push-up", ["chest"], ["triceps", "front_delts"], "bodyweight", "weighted_bodyweight", "push_h", ["shoulder", "wrist"], False),
    ("dip", "Parallel bar dip", ["chest", "triceps"], ["front_delts"], "bodyweight", "bodyweight_reps", "push_v", ["shoulder", "elbow"], False),
    ("weighted_dip", "Weighted dip", ["chest", "triceps"], ["front_delts"], "bodyweight", "weighted_bodyweight", "push_v", ["shoulder", "elbow"], False),
    ("assisted_dip", "Assisted dip", ["chest", "triceps"], ["front_delts"], "machine", "assisted_bodyweight", "push_v", ["shoulder", "elbow"], False),
    # ── shoulders ──
    ("overhead_press", "Barbell overhead press", ["front_delts"], ["triceps", "side_delts", "upper_back"], "barbell", "weight_reps", "push_v", ["shoulder", "elbow", "lower_back"], False),
    ("db_shoulder_press", "Dumbbell shoulder press", ["front_delts"], ["triceps", "side_delts"], "dumbbell", "weight_reps", "push_v", ["shoulder", "elbow"], False),
    ("arnold_press", "Arnold press", ["front_delts", "side_delts"], ["triceps"], "dumbbell", "weight_reps", "push_v", ["shoulder"], False),
    ("shoulder_press_machine", "Machine shoulder press", ["front_delts"], ["triceps", "side_delts"], "machine", "weight_reps", "push_v", ["shoulder", "elbow"], False),
    ("lateral_raise", "Dumbbell lateral raise", ["side_delts"], ["traps"], "dumbbell", "weight_reps", "isolation", ["shoulder"], False),
    ("cable_lateral_raise", "Cable lateral raise", ["side_delts"], [], "cable", "weight_reps", "isolation", ["shoulder"], True),
    ("machine_lateral_raise", "Machine lateral raise", ["side_delts"], [], "machine", "weight_reps", "isolation", ["shoulder"], False),
    ("front_raise", "Front raise", ["front_delts"], [], "dumbbell", "weight_reps", "isolation", ["shoulder"], False),
    ("rear_delt_fly", "Rear delt raise", ["rear_delts"], ["upper_back"], "dumbbell", "weight_reps", "isolation", ["shoulder"], False),
    ("reverse_pec_deck", "Reverse pec deck", ["rear_delts"], ["upper_back"], "machine", "weight_reps", "isolation", ["shoulder"], False),
    ("face_pull", "Face pull", ["rear_delts", "upper_back"], ["traps"], "cable", "weight_reps", "pull_h", ["shoulder"], False),
    ("upright_row", "Upright row", ["side_delts", "traps"], ["biceps"], "barbell", "weight_reps", "pull_v", ["shoulder", "wrist"], False),
    ("barbell_shrug", "Barbell shrug", ["traps"], ["forearms"], "barbell", "weight_reps", "isolation", ["neck"], False),
    ("db_shrug", "Dumbbell shrug", ["traps"], ["forearms"], "dumbbell", "weight_reps", "isolation", ["neck"], False),
    # ── back ──
    ("deadlift", "Deadlift", ["hamstrings", "glutes", "lower_back"], ["upper_back", "traps", "forearms", "quads"], "barbell", "weight_reps", "hinge", ["lower_back", "hip", "knee"], False),
    ("sumo_deadlift", "Sumo deadlift", ["glutes", "quads", "adductors"], ["hamstrings", "lower_back", "traps"], "barbell", "weight_reps", "hinge", ["lower_back", "hip", "knee"], False),
    ("trap_bar_deadlift", "Trap bar deadlift", ["quads", "glutes", "hamstrings"], ["lower_back", "traps"], "trap_bar", "weight_reps", "hinge", ["lower_back", "hip", "knee"], False),
    ("rack_pull", "Rack pull", ["lower_back", "traps", "glutes"], ["hamstrings", "forearms"], "barbell", "weight_reps", "hinge", ["lower_back"], False),
    ("pull_up", "Pull-up", ["lats"], ["biceps", "upper_back", "forearms"], "bodyweight", "bodyweight_reps", "pull_v", ["shoulder", "elbow"], False),
    ("chin_up", "Chin-up", ["lats", "biceps"], ["upper_back"], "bodyweight", "bodyweight_reps", "pull_v", ["shoulder", "elbow"], False),
    ("weighted_pull_up", "Weighted pull-up", ["lats"], ["biceps", "upper_back"], "bodyweight", "weighted_bodyweight", "pull_v", ["shoulder", "elbow"], False),
    ("assisted_pull_up", "Assisted pull-up", ["lats"], ["biceps", "upper_back"], "machine", "assisted_bodyweight", "pull_v", ["shoulder", "elbow"], False),
    ("lat_pulldown", "Lat pulldown", ["lats"], ["biceps", "upper_back"], "cable", "weight_reps", "pull_v", ["shoulder", "elbow"], False),
    ("close_grip_pulldown", "Close-grip lat pulldown", ["lats"], ["biceps", "upper_back"], "cable", "weight_reps", "pull_v", ["shoulder", "elbow"], False),
    ("straight_arm_pulldown", "Straight-arm pulldown", ["lats"], ["triceps"], "cable", "weight_reps", "isolation", ["shoulder"], False),
    ("barbell_row", "Barbell row", ["upper_back", "lats"], ["biceps", "rear_delts", "lower_back"], "barbell", "weight_reps", "pull_h", ["lower_back", "shoulder", "elbow"], False),
    ("pendlay_row", "Pendlay row", ["upper_back", "lats"], ["biceps", "lower_back"], "barbell", "weight_reps", "pull_h", ["lower_back", "shoulder"], False),
    ("db_row", "Dumbbell row", ["lats", "upper_back"], ["biceps", "rear_delts"], "dumbbell", "weight_reps", "pull_h", ["shoulder", "elbow"], True),
    ("seated_cable_row", "Seated cable row", ["upper_back", "lats"], ["biceps", "rear_delts"], "cable", "weight_reps", "pull_h", ["shoulder", "elbow", "lower_back"], False),
    ("t_bar_row", "T-bar row", ["upper_back", "lats"], ["biceps", "lower_back"], "barbell", "weight_reps", "pull_h", ["lower_back", "shoulder"], False),
    ("chest_supported_row", "Chest-supported row", ["upper_back", "lats"], ["biceps", "rear_delts"], "dumbbell", "weight_reps", "pull_h", ["shoulder", "elbow"], False),
    ("machine_row", "Row machine", ["upper_back", "lats"], ["biceps"], "machine", "weight_reps", "pull_h", ["shoulder", "elbow"], False),
    ("inverted_row", "Inverted row", ["upper_back", "lats"], ["biceps", "rear_delts"], "bodyweight", "bodyweight_reps", "pull_h", ["shoulder", "elbow"], False),
    ("back_extension", "Hyperextension", ["lower_back", "glutes"], ["hamstrings"], "bodyweight", "bodyweight_reps", "hinge", ["lower_back"], False),
    ("good_morning", "Good morning", ["hamstrings", "lower_back"], ["glutes"], "barbell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    # ── arms ──
    ("barbell_curl", "Barbell curl", ["biceps"], ["forearms"], "barbell", "weight_reps", "isolation", ["elbow", "wrist"], False),
    ("ez_curl", "EZ bar curl", ["biceps"], ["forearms"], "ez_bar", "weight_reps", "isolation", ["elbow", "wrist"], False),
    ("db_curl", "Dumbbell curl", ["biceps"], ["forearms"], "dumbbell", "weight_reps", "isolation", ["elbow"], False),
    ("hammer_curl", "Hammer curl", ["biceps", "forearms"], [], "dumbbell", "weight_reps", "isolation", ["elbow"], False),
    ("incline_db_curl", "Incline dumbbell curl", ["biceps"], [], "dumbbell", "weight_reps", "isolation", ["elbow", "shoulder"], False),
    ("preacher_curl", "Preacher curl", ["biceps"], ["forearms"], "ez_bar", "weight_reps", "isolation", ["elbow"], False),
    ("cable_curl", "Cable curl", ["biceps"], ["forearms"], "cable", "weight_reps", "isolation", ["elbow"], False),
    ("concentration_curl", "Concentration curl", ["biceps"], [], "dumbbell", "weight_reps", "isolation", ["elbow"], True),
    ("tricep_pushdown", "Cable pushdown", ["triceps"], [], "cable", "weight_reps", "isolation", ["elbow"], False),
    ("rope_pushdown", "Rope pushdown", ["triceps"], [], "cable", "weight_reps", "isolation", ["elbow"], False),
    ("overhead_tricep_extension", "Overhead triceps extension", ["triceps"], [], "cable", "weight_reps", "isolation", ["elbow", "shoulder"], False),
    ("skull_crusher", "Skull crusher", ["triceps"], [], "ez_bar", "weight_reps", "isolation", ["elbow"], False),
    ("db_tricep_extension", "Dumbbell triceps extension", ["triceps"], [], "dumbbell", "weight_reps", "isolation", ["elbow", "shoulder"], False),
    ("tricep_kickback", "Kickback", ["triceps"], [], "dumbbell", "weight_reps", "isolation", ["elbow"], True),
    ("bench_dip", "Bench dip", ["triceps"], ["chest", "front_delts"], "bodyweight", "bodyweight_reps", "push_v", ["shoulder", "elbow", "wrist"], False),
    ("wrist_curl", "Wrist curl", ["forearms"], [], "dumbbell", "weight_reps", "isolation", ["wrist"], False),
    ("reverse_curl", "Reverse curl", ["forearms", "biceps"], [], "barbell", "weight_reps", "isolation", ["wrist", "elbow"], False),
    # ── legs ──
    ("back_squat", "Barbell back squat", ["quads", "glutes"], ["adductors", "hamstrings", "lower_back"], "barbell", "weight_reps", "squat", ["knee", "hip", "lower_back"], False),
    ("front_squat", "Front squat", ["quads"], ["glutes", "abs", "upper_back"], "barbell", "weight_reps", "squat", ["knee", "wrist", "lower_back"], False),
    ("high_bar_squat", "Squat high bar", ["quads", "glutes"], ["adductors"], "barbell", "weight_reps", "squat", ["knee", "hip"], False),
    ("goblet_squat", "Goblet squat", ["quads", "glutes"], ["abs"], "dumbbell", "weight_reps", "squat", ["knee", "hip"], False),
    ("smith_squat", "Smith machine squat", ["quads", "glutes"], [], "smith", "weight_reps", "squat", ["knee", "hip"], False),
    ("hack_squat", "Hack squat", ["quads"], ["glutes"], "machine", "weight_reps", "squat", ["knee"], False),
    ("leg_press", "Leg press", ["quads", "glutes"], ["adductors"], "machine", "weight_reps", "squat", ["knee", "hip"], False),
    ("bodyweight_squat", "Bodyweight squat", ["quads", "glutes"], [], "bodyweight", "bodyweight_reps", "squat", ["knee"], False),
    ("bulgarian_split_squat", "Bulgarian split squat", ["quads", "glutes"], ["adductors"], "dumbbell", "weight_reps", "lunge", ["knee", "hip"], True),
    ("walking_lunge", "Walking lunge", ["quads", "glutes"], ["adductors", "hamstrings"], "dumbbell", "weight_reps", "lunge", ["knee", "hip"], True),
    ("reverse_lunge", "Reverse lunge", ["quads", "glutes"], ["hamstrings"], "dumbbell", "weight_reps", "lunge", ["knee", "hip"], True),
    ("step_up", "Step up", ["quads", "glutes"], [], "dumbbell", "weight_reps", "lunge", ["knee"], True),
    ("leg_extension", "Leg extension", ["quads"], [], "machine", "weight_reps", "isolation", ["knee"], False),
    ("leg_curl_lying", "Lying leg curl", ["hamstrings"], ["calves"], "machine", "weight_reps", "isolation", ["knee"], False),
    ("leg_curl_seated", "Seated leg curl", ["hamstrings"], [], "machine", "weight_reps", "isolation", ["knee"], False),
    ("romanian_deadlift", "Romanian deadlift", ["hamstrings", "glutes"], ["lower_back", "forearms"], "barbell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    ("db_romanian_deadlift", "Dumbbell Romanian deadlift", ["hamstrings", "glutes"], ["lower_back"], "dumbbell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    ("stiff_leg_deadlift", "Stiff-leg deadlift", ["hamstrings"], ["glutes", "lower_back"], "barbell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    ("nordic_curl", "Nordic curl", ["hamstrings"], [], "bodyweight", "bodyweight_reps", "isolation", ["knee"], False),
    ("hip_thrust", "Barbell hip thrust", ["glutes"], ["hamstrings"], "barbell", "weight_reps", "hinge", ["hip", "lower_back"], False),
    ("glute_bridge", "Glute bridge", ["glutes"], ["hamstrings"], "bodyweight", "bodyweight_reps", "hinge", ["hip"], False),
    ("cable_kickback", "Cable kickback", ["glutes"], [], "cable", "weight_reps", "isolation", ["hip"], True),
    ("hip_abduction", "Abductor machine", ["abductors", "glutes"], [], "machine", "weight_reps", "isolation", ["hip"], False),
    ("hip_adduction", "Adductor machine", ["adductors"], [], "machine", "weight_reps", "isolation", ["hip"], False),
    ("standing_calf_raise", "Standing calf raise", ["calves"], [], "machine", "weight_reps", "isolation", ["ankle"], False),
    ("seated_calf_raise", "Seated calf raise", ["calves"], [], "machine", "weight_reps", "isolation", ["ankle"], False),
    ("leg_press_calf_raise", "Leg press calf raise", ["calves"], [], "machine", "weight_reps", "isolation", ["ankle"], False),
    # ── core ──
    ("plank", "Plank", ["abs"], ["obliques", "front_delts"], "bodyweight", "duration", "core", ["lower_back", "shoulder"], False),
    ("side_plank", "Side plank", ["obliques"], ["abs"], "bodyweight", "duration", "core", ["shoulder"], True),
    ("crunch", "Crunch", ["abs"], [], "bodyweight", "bodyweight_reps", "core", ["neck"], False),
    ("cable_crunch", "Cable crunch", ["abs"], ["obliques"], "cable", "weight_reps", "core", ["lower_back"], False),
    ("hanging_leg_raise", "Hanging leg raise", ["abs"], ["obliques", "forearms"], "bodyweight", "bodyweight_reps", "core", ["shoulder", "lower_back"], False),
    ("lying_leg_raise", "Lying leg raise", ["abs"], [], "bodyweight", "bodyweight_reps", "core", ["lower_back"], False),
    ("ab_wheel", "Ab wheel", ["abs"], ["lats", "obliques"], "other", "bodyweight_reps", "core", ["lower_back", "shoulder"], False),
    ("russian_twist", "Russian twist", ["obliques"], ["abs"], "bodyweight", "bodyweight_reps", "core", ["lower_back"], False),
    ("pallof_press", "Pallof press", ["obliques", "abs"], [], "cable", "weight_reps", "core", [], True),
    ("dead_bug", "Dead bug", ["abs"], [], "bodyweight", "bodyweight_reps", "core", [], False),
    ("hanging_knee_raise", "Hanging knee raise", ["abs"], ["forearms"], "bodyweight", "bodyweight_reps", "core", ["shoulder"], False),
    ("decline_sit_up", "Decline sit-up", ["abs"], [], "bodyweight", "bodyweight_reps", "core", ["lower_back", "neck"], False),
    # ── full body / carries / kettlebell ──
    ("farmer_carry", "Farmer walk", ["forearms", "traps"], ["abs", "glutes"], "dumbbell", "weight_duration", "carry", ["wrist"], False),
    ("kb_swing", "Kettlebell swing", ["glutes", "hamstrings"], ["lower_back", "abs"], "kettlebell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    ("kb_goblet_squat", "Kettlebell goblet squat", ["quads", "glutes"], ["abs"], "kettlebell", "weight_reps", "squat", ["knee", "hip"], False),
    ("power_clean", "Power clean", ["glutes", "hamstrings", "traps"], ["quads", "upper_back", "forearms"], "barbell", "weight_reps", "hinge", ["lower_back", "wrist", "knee"], False),
    ("thruster", "Thruster", ["quads", "front_delts"], ["glutes", "triceps"], "barbell", "weight_reps", "squat", ["knee", "shoulder"], False),
    ("sled_push", "Sled push", ["quads", "glutes"], ["calves"], "other", "distance_duration", "carry", ["knee"], False),
    ("burpee", "Burpee", ["quads", "chest"], ["abs", "triceps"], "bodyweight", "reps_only", "squat", ["wrist", "knee"], False),
    ("band_pull_apart", "Band pull-apart", ["rear_delts", "upper_back"], [], "band", "reps_only", "pull_h", ["shoulder"], False),
]


def exercise_id(slug: str) -> str:
    return str(uuid.uuid5(NAMESPACE, slug))


def seed() -> list[dict]:
    """Rows ready for the store (kind ``exercise``)."""
    out = []
    for i, (slug, name, prim, sec, equip, kind, pattern, joints, uni) in enumerate(_E):
        out.append({"id": exercise_id(slug), "slug": slug, "name": name, "aliases": list(words(f"hercules.exercise.{slug}")),
                    "primary_muscles": list(prim), "secondary_muscles": list(sec), "equipment": equip,
                    "kind": kind, "movement_pattern": pattern, "stress_joints": list(joints),
                    "unilateral": bool(uni), "is_custom": False, "archived": False, "notes": "",
                    "instructions": "", "increment_kg": None})
    return out


def group_of(muscle: str) -> str:
    for group, muscles in MUSCLE_GROUPS.items():
        if muscle in muscles:
            return group
    return ""
