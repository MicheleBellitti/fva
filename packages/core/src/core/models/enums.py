from enum import IntEnum, StrEnum


class Cls(IntEnum):  # tracks.cls
    PLAYER = 0
    GOALKEEPER = 1
    REFEREE = 2
    BALL = 3


class ViewType(StrEnum):  # video_segments.view_type
    TACTICAL = "tactical"  # campo largo, omografia possibile
    REPLAY = "replay"
    CLOSEUP = "closeup"
    CROWD = "crowd"
    GRAPHIC = "graphic"  # grafica a tutto schermo: formazioni, statistiche
    UNKNOWN = "unknown"  # il classificatore non ha deciso


class CameraType(StrEnum):  # matches.camera_type, seleziona @config.when
    BROADCAST = "broadcast"
    TACTICAL_FIXED = "tactical_fixed"


class Team(IntEnum):  # team in Parquet e in Postgres
    A = 0  # la squadra analizzata, vedi matches.team_a_side
    B = 1


class EventType(StrEnum):  # events.type — vedi ADR-013
    CORNER = "corner"
    THROW_IN = "throw_in"
    GOAL_KICK = "goal_kick"
    KICKOFF = "kickoff"
    TURNOVER = "turnover"
    SHOT = "shot"
    CROSS = "cross"
    PASS_FINAL_THIRD = "pass_final_third"
    COUNTER_ATTACK = "counter_attack"
    PRESS_TRIGGER = "press_trigger"


class MetricName(StrEnum):  # team_metrics.metric
    DEFENSIVE_LINE_HEIGHT = "defensive_line_height"
    TEAM_WIDTH = "team_width"
    COMPACTNESS = "compactness"
    POSSESSION_SHARE = "possession_share"
    PPDA_PROXY = "ppda_proxy"


class Zone(StrEnum):  # solo DSL, mai in colonna — §2.4
    DEFENSIVE_THIRD = "defensive_third"
    MIDDLE_THIRD = "middle_third"
    FINAL_THIRD = "final_third"
    LEFT_FLANK = "left_flank"
    CENTER = "center"
    RIGHT_FLANK = "right_flank"
    BOX = "box"


class EventSource(StrEnum):  # events.source
    DETECTOR = "detector"  # emesso da un detector del registry, sul tracking
    DERIVED = "derived"  # combinazione di altri eventi o possessi
    MANUAL = "manual"  # inserito o corretto da una persona


class EventStatus(StrEnum):  # events.status
    PROVISIONAL = "provisional"
    CONFIRMED = "confirmed"  # unico valore ammesso fino a M4
    RETRACTED = "retracted"


class PossessionSource(StrEnum):  # possessions.source
    BALL = "ball"  # D3: dalla palla e dal portatore
    FALLBACK = "fallback"  # D4: palla assente, movimento collettivo


class PossessionOutcome(StrEnum):  # possessions.outcome
    SHOT = "shot"
    TURNOVER = "turnover"  # palla persa in gioco
    OUT_OF_PLAY = "out_of_play"
    END_OF_HALF = "end_of_half"
    UNKNOWN = "unknown"


class MatchStatus(StrEnum):  # matches.status
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class JobKind(StrEnum):  # jobs.kind
    INGEST = "ingest"
    REPROCESS = "reprocess"


class JobStatus(StrEnum):  # jobs.status
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class EvalKind(StrEnum):  # eval_cases.kind
    PERCEPTION = "perception"
    ASSISTANT = "assistant"


class EvalCaseStatus(StrEnum):  # eval_cases.status
    CANDIDATE = "candidate"  # proposto, ad esempio da un feedback negativo
    ACTIVE = "active"
    RETIRED = "retired"


class TeamSide(StrEnum):  # matches.team_a_side
    HOME = "home"
    AWAY = "away"
