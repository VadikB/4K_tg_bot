from enum import StrEnum


class LifecycleStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    RETIRED = "retired"


class ProjectStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ASSESSMENT = "assessment"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class ParticipantStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    REMOVED = "removed"
    COMPLETED = "completed"


class AssignmentStatus(StrEnum):
    ASSIGNED = "assigned"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DeliveryStatus(StrEnum):
    RESERVED = "reserved"
    ISSUED = "issued"
    COMPLETED = "completed"
    FAILED = "failed"


class CrispDmStage(StrEnum):
    BUSINESS_UNDERSTANDING = "business_understanding"
    DATA_UNDERSTANDING = "data_understanding"
    DATA_PREPARATION = "data_preparation"
    MODELING = "modeling"
    EVALUATION = "evaluation"
    DEPLOYMENT = "deployment"

