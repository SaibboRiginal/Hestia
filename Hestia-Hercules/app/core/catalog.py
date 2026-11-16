"""Built-in exercise library (seeded once, ids stable everywhere: uuid5 of the slug).

Each entry: slug, English name (shown translated), aliases (English and Italian, for matching), primary muscles, secondary muscles, equipment, kind,
movement pattern, stressed joints (pain rule), unilateral. The user's own exercises live next to these
(``is_custom``) and seeded ones can be edited or archived like any other.
"""
from __future__ import annotations

import uuid

NAMESPACE = uuid.UUID("6f1c2a43-0b7e-4d0a-9f55-4f3c8e9a1b20")

MUSCLES = {
    "chest": "Chest", "front_delts": "Front delt", "side_delts": "Side delt",
    "rear_delts": "Rear delt", "triceps": "Triceps", "biceps": "Biceps", "forearms": "Forearms",
    "lats": "Lats", "upper_back": "Upper back", "traps": "Traps", "lower_back": "Lower back",
    "abs": "Abs", "obliques": "Obliques", "glutes": "Glutes", "quads": "Quads",
    "hamstrings": "Hamstrings", "adductors": "Adductors", "abductors": "Abductors", "calves": "Calves",
    "neck": "Neck",
}
# Coarse groups for weekly volume and goals ("schiena 2/settimana").
MUSCLE_GROUPS = {
    "petto": ["chest"], "spalle": ["front_delts", "side_delts", "rear_delts"],
    "braccia": ["biceps", "triceps", "forearms"], "schiena": ["lats", "upper_back", "traps", "lower_back"],
    "core": ["abs", "obliques"], "gambe": ["quads", "hamstrings", "glutes", "adductors", "abductors", "calves"],
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

# slug, name, aliases, primary, secondary, equipment, kind, pattern, joints, unilateral
_E = [
    # ── chest ──
    ("bench_press", "Barbell bench press", ["panca piana con bilanciere", "bench press", "panca"], ["chest"], ["front_delts", "triceps"], "barbell", "weight_reps", "push_h", ["shoulder", "elbow", "wrist"], False),
    ("incline_bench_press", "Barbell incline bench press", ["panca inclinata con bilanciere", "incline bench press"], ["chest", "front_delts"], ["triceps"], "barbell", "weight_reps", "push_h", ["shoulder", "elbow", "wrist"], False),
    ("decline_bench_press", "Barbell decline bench press", ["panca declinata con bilanciere", "decline bench press"], ["chest"], ["triceps", "front_delts"], "barbell", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("close_grip_bench_press", "Close-grip bench press", ["panca presa stretta", "close grip bench press"], ["triceps", "chest"], ["front_delts"], "barbell", "weight_reps", "push_h", ["elbow", "wrist", "shoulder"], False),
    ("db_bench_press", "Dumbbell bench press", ["panca piana con manubri", "dumbbell bench press"], ["chest"], ["front_delts", "triceps"], "dumbbell", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("db_incline_press", "Incline dumbbell press", ["panca inclinata con manubri", "incline dumbbell press"], ["chest", "front_delts"], ["triceps"], "dumbbell", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("db_fly", "Dumbbell fly", ["croci con manubri", "dumbbell fly"], ["chest"], ["front_delts"], "dumbbell", "weight_reps", "isolation", ["shoulder"], False),
    ("cable_fly", "Cable fly", ["croci ai cavi", "cable crossover", "cable fly"], ["chest"], ["front_delts"], "cable", "weight_reps", "isolation", ["shoulder"], False),
    ("pec_deck", "Pectoral machine", ["pec deck", "chest fly machine"], ["chest"], [], "machine", "weight_reps", "isolation", ["shoulder"], False),
    ("chest_press_machine", "Chest press", ["chest press machine"], ["chest"], ["triceps", "front_delts"], "machine", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("smith_bench_press", "Smith machine bench press", ["panca piana al multipower", "smith machine bench press"], ["chest"], ["triceps", "front_delts"], "smith", "weight_reps", "push_h", ["shoulder", "elbow"], False),
    ("push_up", "Push-up", ["piegamenti", "push up", "flessioni"], ["chest"], ["triceps", "front_delts", "abs"], "bodyweight", "bodyweight_reps", "push_h", ["shoulder", "wrist", "elbow"], False),
    ("weighted_push_up", "Weighted push-up", ["piegamenti zavorrati", "weighted push up"], ["chest"], ["triceps", "front_delts"], "bodyweight", "weighted_bodyweight", "push_h", ["shoulder", "wrist"], False),
    ("dip", "Parallel bar dip", ["dip alle parallele", "dips", "chest dip"], ["chest", "triceps"], ["front_delts"], "bodyweight", "bodyweight_reps", "push_v", ["shoulder", "elbow"], False),
    ("weighted_dip", "Weighted dip", ["dip zavorrati", "weighted dip"], ["chest", "triceps"], ["front_delts"], "bodyweight", "weighted_bodyweight", "push_v", ["shoulder", "elbow"], False),
    ("assisted_dip", "Assisted dip", ["dip assistiti", "assisted dip machine"], ["chest", "triceps"], ["front_delts"], "machine", "assisted_bodyweight", "push_v", ["shoulder", "elbow"], False),
    # ── shoulders ──
    ("overhead_press", "Barbell overhead press", ["lento avanti con bilanciere", "overhead press", "military press", "ohp"], ["front_delts"], ["triceps", "side_delts", "upper_back"], "barbell", "weight_reps", "push_v", ["shoulder", "elbow", "lower_back"], False),
    ("db_shoulder_press", "Dumbbell shoulder press", ["shoulder press con manubri", "dumbbell shoulder press"], ["front_delts"], ["triceps", "side_delts"], "dumbbell", "weight_reps", "push_v", ["shoulder", "elbow"], False),
    ("arnold_press", "Arnold press", ["arnold press"], ["front_delts", "side_delts"], ["triceps"], "dumbbell", "weight_reps", "push_v", ["shoulder"], False),
    ("shoulder_press_machine", "Machine shoulder press", ["shoulder press alla macchina", "shoulder press machine"], ["front_delts"], ["triceps", "side_delts"], "machine", "weight_reps", "push_v", ["shoulder", "elbow"], False),
    ("lateral_raise", "Dumbbell lateral raise", ["alzate laterali con manubri", "lateral raise", "side raise"], ["side_delts"], ["traps"], "dumbbell", "weight_reps", "isolation", ["shoulder"], False),
    ("cable_lateral_raise", "Cable lateral raise", ["alzate laterali al cavo", "cable lateral raise"], ["side_delts"], [], "cable", "weight_reps", "isolation", ["shoulder"], True),
    ("machine_lateral_raise", "Machine lateral raise", ["alzate laterali alla macchina", "lateral raise machine"], ["side_delts"], [], "machine", "weight_reps", "isolation", ["shoulder"], False),
    ("front_raise", "Front raise", ["alzate frontali", "front raise"], ["front_delts"], [], "dumbbell", "weight_reps", "isolation", ["shoulder"], False),
    ("rear_delt_fly", "Rear delt raise", ["alzate posteriori", "rear delt fly", "reverse fly"], ["rear_delts"], ["upper_back"], "dumbbell", "weight_reps", "isolation", ["shoulder"], False),
    ("reverse_pec_deck", "Reverse pec deck", ["reverse pec deck", "rear delt machine"], ["rear_delts"], ["upper_back"], "machine", "weight_reps", "isolation", ["shoulder"], False),
    ("face_pull", "Face pull", ["face pull"], ["rear_delts", "upper_back"], ["traps"], "cable", "weight_reps", "pull_h", ["shoulder"], False),
    ("upright_row", "Upright row", ["tirate al mento", "upright row"], ["side_delts", "traps"], ["biceps"], "barbell", "weight_reps", "pull_v", ["shoulder", "wrist"], False),
    ("barbell_shrug", "Barbell shrug", ["scrollate con bilanciere", "barbell shrug"], ["traps"], ["forearms"], "barbell", "weight_reps", "isolation", ["neck"], False),
    ("db_shrug", "Dumbbell shrug", ["scrollate con manubri", "dumbbell shrug"], ["traps"], ["forearms"], "dumbbell", "weight_reps", "isolation", ["neck"], False),
    # ── back ──
    ("deadlift", "Deadlift", ["stacco da terra", "deadlift", "stacco"], ["hamstrings", "glutes", "lower_back"], ["upper_back", "traps", "forearms", "quads"], "barbell", "weight_reps", "hinge", ["lower_back", "hip", "knee"], False),
    ("sumo_deadlift", "Sumo deadlift", ["stacco sumo", "sumo deadlift"], ["glutes", "quads", "adductors"], ["hamstrings", "lower_back", "traps"], "barbell", "weight_reps", "hinge", ["lower_back", "hip", "knee"], False),
    ("trap_bar_deadlift", "Trap bar deadlift", ["stacco con trap bar", "trap bar deadlift", "hex bar deadlift"], ["quads", "glutes", "hamstrings"], ["lower_back", "traps"], "trap_bar", "weight_reps", "hinge", ["lower_back", "hip", "knee"], False),
    ("rack_pull", "Rack pull", ["rack pull"], ["lower_back", "traps", "glutes"], ["hamstrings", "forearms"], "barbell", "weight_reps", "hinge", ["lower_back"], False),
    ("pull_up", "Pull-up", ["trazioni alla sbarra", "pull up", "trazioni"], ["lats"], ["biceps", "upper_back", "forearms"], "bodyweight", "bodyweight_reps", "pull_v", ["shoulder", "elbow"], False),
    ("chin_up", "Chin-up", ["trazioni presa supina", "chin up"], ["lats", "biceps"], ["upper_back"], "bodyweight", "bodyweight_reps", "pull_v", ["shoulder", "elbow"], False),
    ("weighted_pull_up", "Weighted pull-up", ["trazioni zavorrate", "weighted pull up"], ["lats"], ["biceps", "upper_back"], "bodyweight", "weighted_bodyweight", "pull_v", ["shoulder", "elbow"], False),
    ("assisted_pull_up", "Assisted pull-up", ["trazioni assistite", "assisted pull up", "gravitron"], ["lats"], ["biceps", "upper_back"], "machine", "assisted_bodyweight", "pull_v", ["shoulder", "elbow"], False),
    ("lat_pulldown", "Lat pulldown", ["lat machine avanti", "lat pulldown"], ["lats"], ["biceps", "upper_back"], "cable", "weight_reps", "pull_v", ["shoulder", "elbow"], False),
    ("close_grip_pulldown", "Close-grip lat pulldown", ["lat machine presa stretta", "close grip lat pulldown", "v-bar pulldown"], ["lats"], ["biceps", "upper_back"], "cable", "weight_reps", "pull_v", ["shoulder", "elbow"], False),
    ("straight_arm_pulldown", "Straight-arm pulldown", ["pulldown a braccia tese", "straight arm pulldown"], ["lats"], ["triceps"], "cable", "weight_reps", "isolation", ["shoulder"], False),
    ("barbell_row", "Barbell row", ["rematore con bilanciere", "barbell row", "bent over row"], ["upper_back", "lats"], ["biceps", "rear_delts", "lower_back"], "barbell", "weight_reps", "pull_h", ["lower_back", "shoulder", "elbow"], False),
    ("pendlay_row", "Pendlay row", ["pendlay row"], ["upper_back", "lats"], ["biceps", "lower_back"], "barbell", "weight_reps", "pull_h", ["lower_back", "shoulder"], False),
    ("db_row", "Dumbbell row", ["rematore con manubrio", "dumbbell row", "one arm row"], ["lats", "upper_back"], ["biceps", "rear_delts"], "dumbbell", "weight_reps", "pull_h", ["shoulder", "elbow"], True),
    ("seated_cable_row", "Seated cable row", ["pulley basso", "seated cable row"], ["upper_back", "lats"], ["biceps", "rear_delts"], "cable", "weight_reps", "pull_h", ["shoulder", "elbow", "lower_back"], False),
    ("t_bar_row", "T-bar row", ["t bar row"], ["upper_back", "lats"], ["biceps", "lower_back"], "barbell", "weight_reps", "pull_h", ["lower_back", "shoulder"], False),
    ("chest_supported_row", "Chest-supported row", ["rematore con petto appoggiato", "chest supported row", "seal row"], ["upper_back", "lats"], ["biceps", "rear_delts"], "dumbbell", "weight_reps", "pull_h", ["shoulder", "elbow"], False),
    ("machine_row", "Row machine", ["row machine"], ["upper_back", "lats"], ["biceps"], "machine", "weight_reps", "pull_h", ["shoulder", "elbow"], False),
    ("inverted_row", "Inverted row", ["rematore inverso", "inverted row", "australian pull up"], ["upper_back", "lats"], ["biceps", "rear_delts"], "bodyweight", "bodyweight_reps", "pull_h", ["shoulder", "elbow"], False),
    ("back_extension", "Hyperextension", ["back extension", "hyperextension"], ["lower_back", "glutes"], ["hamstrings"], "bodyweight", "bodyweight_reps", "hinge", ["lower_back"], False),
    ("good_morning", "Good morning", ["good morning"], ["hamstrings", "lower_back"], ["glutes"], "barbell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    # ── arms ──
    ("barbell_curl", "Barbell curl", ["curl con bilanciere", "barbell curl"], ["biceps"], ["forearms"], "barbell", "weight_reps", "isolation", ["elbow", "wrist"], False),
    ("ez_curl", "EZ bar curl", ["curl con bilanciere ez", "ez bar curl"], ["biceps"], ["forearms"], "ez_bar", "weight_reps", "isolation", ["elbow", "wrist"], False),
    ("db_curl", "Dumbbell curl", ["curl con manubri", "dumbbell curl"], ["biceps"], ["forearms"], "dumbbell", "weight_reps", "isolation", ["elbow"], False),
    ("hammer_curl", "Hammer curl", ["curl a martello", "hammer curl"], ["biceps", "forearms"], [], "dumbbell", "weight_reps", "isolation", ["elbow"], False),
    ("incline_db_curl", "Incline dumbbell curl", ["curl su panca inclinata", "incline dumbbell curl"], ["biceps"], [], "dumbbell", "weight_reps", "isolation", ["elbow", "shoulder"], False),
    ("preacher_curl", "Preacher curl", ["curl alla panca scott", "preacher curl"], ["biceps"], ["forearms"], "ez_bar", "weight_reps", "isolation", ["elbow"], False),
    ("cable_curl", "Cable curl", ["curl ai cavi", "cable curl"], ["biceps"], ["forearms"], "cable", "weight_reps", "isolation", ["elbow"], False),
    ("concentration_curl", "Concentration curl", ["curl di concentrazione", "concentration curl"], ["biceps"], [], "dumbbell", "weight_reps", "isolation", ["elbow"], True),
    ("tricep_pushdown", "Cable pushdown", ["pushdown ai cavi", "tricep pushdown", "pushdown"], ["triceps"], [], "cable", "weight_reps", "isolation", ["elbow"], False),
    ("rope_pushdown", "Rope pushdown", ["pushdown con corda", "rope pushdown"], ["triceps"], [], "cable", "weight_reps", "isolation", ["elbow"], False),
    ("overhead_tricep_extension", "Overhead triceps extension", ["french press sopra la testa", "overhead tricep extension", "overhead cable extension"], ["triceps"], [], "cable", "weight_reps", "isolation", ["elbow", "shoulder"], False),
    ("skull_crusher", "Skull crusher", ["french press con ez", "skull crusher", "lying tricep extension"], ["triceps"], [], "ez_bar", "weight_reps", "isolation", ["elbow"], False),
    ("db_tricep_extension", "Dumbbell triceps extension", ["estensioni tricipiti con manubrio", "dumbbell tricep extension"], ["triceps"], [], "dumbbell", "weight_reps", "isolation", ["elbow", "shoulder"], False),
    ("tricep_kickback", "Kickback", ["tricep kickback"], ["triceps"], [], "dumbbell", "weight_reps", "isolation", ["elbow"], True),
    ("bench_dip", "Bench dip", ["dip su panca", "bench dip"], ["triceps"], ["chest", "front_delts"], "bodyweight", "bodyweight_reps", "push_v", ["shoulder", "elbow", "wrist"], False),
    ("wrist_curl", "Wrist curl", ["curl per polsi", "wrist curl"], ["forearms"], [], "dumbbell", "weight_reps", "isolation", ["wrist"], False),
    ("reverse_curl", "Reverse curl", ["curl inverso", "reverse curl"], ["forearms", "biceps"], [], "barbell", "weight_reps", "isolation", ["wrist", "elbow"], False),
    # ── legs ──
    ("back_squat", "Barbell back squat", ["squat con bilanciere", "back squat", "squat"], ["quads", "glutes"], ["adductors", "hamstrings", "lower_back"], "barbell", "weight_reps", "squat", ["knee", "hip", "lower_back"], False),
    ("front_squat", "Front squat", ["front squat"], ["quads"], ["glutes", "abs", "upper_back"], "barbell", "weight_reps", "squat", ["knee", "wrist", "lower_back"], False),
    ("high_bar_squat", "Squat high bar", ["high bar squat"], ["quads", "glutes"], ["adductors"], "barbell", "weight_reps", "squat", ["knee", "hip"], False),
    ("goblet_squat", "Goblet squat", ["goblet squat"], ["quads", "glutes"], ["abs"], "dumbbell", "weight_reps", "squat", ["knee", "hip"], False),
    ("smith_squat", "Smith machine squat", ["squat al multipower", "smith machine squat"], ["quads", "glutes"], [], "smith", "weight_reps", "squat", ["knee", "hip"], False),
    ("hack_squat", "Hack squat", ["hack squat"], ["quads"], ["glutes"], "machine", "weight_reps", "squat", ["knee"], False),
    ("leg_press", "Leg press", ["leg press", "pressa"], ["quads", "glutes"], ["adductors"], "machine", "weight_reps", "squat", ["knee", "hip"], False),
    ("bodyweight_squat", "Bodyweight squat", ["squat a corpo libero", "air squat", "bodyweight squat"], ["quads", "glutes"], [], "bodyweight", "bodyweight_reps", "squat", ["knee"], False),
    ("bulgarian_split_squat", "Bulgarian split squat", ["bulgarian split squat"], ["quads", "glutes"], ["adductors"], "dumbbell", "weight_reps", "lunge", ["knee", "hip"], True),
    ("walking_lunge", "Walking lunge", ["affondi in camminata", "walking lunge"], ["quads", "glutes"], ["adductors", "hamstrings"], "dumbbell", "weight_reps", "lunge", ["knee", "hip"], True),
    ("reverse_lunge", "Reverse lunge", ["affondi indietro", "reverse lunge"], ["quads", "glutes"], ["hamstrings"], "dumbbell", "weight_reps", "lunge", ["knee", "hip"], True),
    ("step_up", "Step up", ["step up"], ["quads", "glutes"], [], "dumbbell", "weight_reps", "lunge", ["knee"], True),
    ("leg_extension", "Leg extension", ["leg extension"], ["quads"], [], "machine", "weight_reps", "isolation", ["knee"], False),
    ("leg_curl_lying", "Lying leg curl", ["leg curl sdraiato", "lying leg curl"], ["hamstrings"], ["calves"], "machine", "weight_reps", "isolation", ["knee"], False),
    ("leg_curl_seated", "Seated leg curl", ["leg curl seduto", "seated leg curl"], ["hamstrings"], [], "machine", "weight_reps", "isolation", ["knee"], False),
    ("romanian_deadlift", "Romanian deadlift", ["stacco rumeno", "romanian deadlift", "rdl"], ["hamstrings", "glutes"], ["lower_back", "forearms"], "barbell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    ("db_romanian_deadlift", "Dumbbell Romanian deadlift", ["stacco rumeno con manubri", "dumbbell romanian deadlift"], ["hamstrings", "glutes"], ["lower_back"], "dumbbell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    ("stiff_leg_deadlift", "Stiff-leg deadlift", ["stacco a gambe tese", "stiff leg deadlift"], ["hamstrings"], ["glutes", "lower_back"], "barbell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    ("nordic_curl", "Nordic curl", ["nordic hamstring curl"], ["hamstrings"], [], "bodyweight", "bodyweight_reps", "isolation", ["knee"], False),
    ("hip_thrust", "Barbell hip thrust", ["hip thrust con bilanciere", "hip thrust"], ["glutes"], ["hamstrings"], "barbell", "weight_reps", "hinge", ["hip", "lower_back"], False),
    ("glute_bridge", "Glute bridge", ["ponte glutei", "glute bridge"], ["glutes"], ["hamstrings"], "bodyweight", "bodyweight_reps", "hinge", ["hip"], False),
    ("cable_kickback", "Cable kickback", ["slanci ai cavi", "cable glute kickback"], ["glutes"], [], "cable", "weight_reps", "isolation", ["hip"], True),
    ("hip_abduction", "Abductor machine", ["hip abduction machine"], ["abductors", "glutes"], [], "machine", "weight_reps", "isolation", ["hip"], False),
    ("hip_adduction", "Adductor machine", ["hip adduction machine"], ["adductors"], [], "machine", "weight_reps", "isolation", ["hip"], False),
    ("standing_calf_raise", "Standing calf raise", ["calf in piedi", "standing calf raise"], ["calves"], [], "machine", "weight_reps", "isolation", ["ankle"], False),
    ("seated_calf_raise", "Seated calf raise", ["calf seduto", "seated calf raise"], ["calves"], [], "machine", "weight_reps", "isolation", ["ankle"], False),
    ("leg_press_calf_raise", "Leg press calf raise", ["calf alla leg press", "calf press"], ["calves"], [], "machine", "weight_reps", "isolation", ["ankle"], False),
    # ── core ──
    ("plank", "Plank", ["plank"], ["abs"], ["obliques", "front_delts"], "bodyweight", "duration", "core", ["lower_back", "shoulder"], False),
    ("side_plank", "Side plank", ["plank laterale", "side plank"], ["obliques"], ["abs"], "bodyweight", "duration", "core", ["shoulder"], True),
    ("crunch", "Crunch", ["crunch"], ["abs"], [], "bodyweight", "bodyweight_reps", "core", ["neck"], False),
    ("cable_crunch", "Cable crunch", ["crunch ai cavi", "cable crunch"], ["abs"], ["obliques"], "cable", "weight_reps", "core", ["lower_back"], False),
    ("hanging_leg_raise", "Hanging leg raise", ["sollevamento gambe alla sbarra", "hanging leg raise"], ["abs"], ["obliques", "forearms"], "bodyweight", "bodyweight_reps", "core", ["shoulder", "lower_back"], False),
    ("lying_leg_raise", "Lying leg raise", ["sollevamento gambe a terra", "lying leg raise"], ["abs"], [], "bodyweight", "bodyweight_reps", "core", ["lower_back"], False),
    ("ab_wheel", "Ab wheel", ["ab wheel rollout"], ["abs"], ["lats", "obliques"], "other", "bodyweight_reps", "core", ["lower_back", "shoulder"], False),
    ("russian_twist", "Russian twist", ["russian twist"], ["obliques"], ["abs"], "bodyweight", "bodyweight_reps", "core", ["lower_back"], False),
    ("pallof_press", "Pallof press", ["pallof press"], ["obliques", "abs"], [], "cable", "weight_reps", "core", [], True),
    ("dead_bug", "Dead bug", ["dead bug"], ["abs"], [], "bodyweight", "bodyweight_reps", "core", [], False),
    ("hanging_knee_raise", "Hanging knee raise", ["ginocchia al petto alla sbarra", "hanging knee raise"], ["abs"], ["forearms"], "bodyweight", "bodyweight_reps", "core", ["shoulder"], False),
    ("decline_sit_up", "Decline sit-up", ["sit up su panca declinata", "decline sit up"], ["abs"], [], "bodyweight", "bodyweight_reps", "core", ["lower_back", "neck"], False),
    # ── full body / carries / kettlebell ──
    ("farmer_carry", "Farmer walk", ["farmer carry", "farmer walk"], ["forearms", "traps"], ["abs", "glutes"], "dumbbell", "weight_duration", "carry", ["wrist"], False),
    ("kb_swing", "Kettlebell swing", ["swing con kettlebell", "kettlebell swing"], ["glutes", "hamstrings"], ["lower_back", "abs"], "kettlebell", "weight_reps", "hinge", ["lower_back", "hip"], False),
    ("kb_goblet_squat", "Kettlebell goblet squat", ["goblet squat con kettlebell", "kettlebell goblet squat"], ["quads", "glutes"], ["abs"], "kettlebell", "weight_reps", "squat", ["knee", "hip"], False),
    ("power_clean", "Power clean", ["girata al petto", "power clean"], ["glutes", "hamstrings", "traps"], ["quads", "upper_back", "forearms"], "barbell", "weight_reps", "hinge", ["lower_back", "wrist", "knee"], False),
    ("thruster", "Thruster", ["thruster"], ["quads", "front_delts"], ["glutes", "triceps"], "barbell", "weight_reps", "squat", ["knee", "shoulder"], False),
    ("sled_push", "Sled push", ["spinta slitta", "sled push"], ["quads", "glutes"], ["calves"], "other", "distance_duration", "carry", ["knee"], False),
    ("burpee", "Burpee", ["burpee"], ["quads", "chest"], ["abs", "triceps"], "bodyweight", "reps_only", "squat", ["wrist", "knee"], False),
    ("band_pull_apart", "Band pull-apart", ["pull apart con elastico", "band pull apart"], ["rear_delts", "upper_back"], [], "band", "reps_only", "pull_h", ["shoulder"], False),
]


def exercise_id(slug: str) -> str:
    return str(uuid.uuid5(NAMESPACE, slug))


def seed() -> list[dict]:
    """Rows ready for the store (kind ``exercise``)."""
    out = []
    for i, (slug, name, aliases, prim, sec, equip, kind, pattern, joints, uni) in enumerate(_E):
        out.append({"id": exercise_id(slug), "slug": slug, "name": name, "aliases": list(aliases),
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
