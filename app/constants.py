from enum import StrEnum


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


class FeedType(StrEnum):
    PERSONALIZED = "personalized"
    POPULAR = "popular"
    EXPLORE = "explore"


class EventType(StrEnum):
    IMPRESSION = "impression"
    CLICK = "click"
    LIKE = "like"
    NOT_INTERESTED = "not_interested"


class ItemStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class OperationType(StrEnum):
    FORCE = "force"
    OFFLINE = "offline"
    RESTORE = "restore"


class OperationScope(StrEnum):
    ALL = "all"
    USER = "user"
    FEED = "feed"


class ModelStatus(StrEnum):
    CANDIDATE = "candidate"
    PUBLISHED = "published"
    FAILED = "failed"

