from typing import NewType, Annotated
from pydantic import Field

StrUUID = NewType("StrUUID", Annotated[str, Field(description="UUID in str view")])

LocalFilePath = NewType("LocalFilePath", Annotated[str, Field(description="Full Path")])
Timestamp = NewType("Timestamp", Annotated[str, Field(description="MM:SS format")])
