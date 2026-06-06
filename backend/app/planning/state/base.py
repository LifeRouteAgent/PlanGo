from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

RequestType = Literal[
    "simple_qa", "single_category_recommend", "full_itinerary_plan", "plan_adjustment"
]
LogicalCategory = Literal[
    "restaurant", "activity", "attraction", "shopping", "entertainment", "fitness", "beauty"
]

PHYSICAL_TABLES: dict[str, str] = {
    "restaurant": "poi_restaurant",
    "activity": "poi_activities",
    "attraction": "poi_attractions",
    "shopping": "poi_shoppings",
    "entertainment": "poi_entertainment",
    "fitness": "poi_fitness",
    "beauty": "poi_beauty",
}
LEGACY_CATEGORIES = {category: f"poi_{category}" for category in PHYSICAL_TABLES}


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

