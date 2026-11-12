from pydantic import BaseModel, ConfigDict, Field, FiniteFloat


class FactorConversion(BaseModel):
 model_config = ConfigDict(extra='forbid')
 factor_id: str = Field(min_length=1, max_length=32)
 scale: FiniteFloat = Field(gt=0, description='正比例缩放系数 x_new = scale*x_old + offset')
 offset: FiniteFloat = 0
 new_unit: str = Field(min_length=1, max_length=30)


class MigrationRequest(BaseModel):
 model_config = ConfigDict(extra='forbid')
 source_model_id: str
 source_space_id: str
 new_model_name: str = Field(min_length=2, max_length=180)
 new_space_name: str = Field(min_length=2, max_length=180)
 description: str = Field(default='', max_length=3000)
 conversions: list[FactorConversion] = Field(min_length=1, max_length=6)
