from typing import Literal

from pydantic import BaseModel, ConfigDict

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


class StateModel(BaseModel):
    # `ConfigDict(extra="forbid")` 含义是禁止传入模型中未定义的额外字段
    model_config = ConfigDict(extra="forbid")
