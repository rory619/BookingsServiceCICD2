from typing import Annotated
from annotated_types import Ge
from pydantic import BaseModel, ConfigDict, StringConstraints
 
# ---------- Reusable type aliases ---------- 
StatusStr = Annotated[str, StringConstraints(min_length=1, max_length=100)] 
PositiveInt = Annotated[int, Ge(1)]
 

 
class BookingCreate(BaseModel): 
   user_id: int
   course_id: PositiveInt
   status: StatusStr = "pending"

class BookingRead(BaseModel): 
   id: int
   user_id: PositiveInt
   course_id: PositiveInt
   status: StatusStr 

   
   model_config = ConfigDict(from_attributes=True) 
  