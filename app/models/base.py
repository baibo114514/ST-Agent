"""
数据库模型基类 - 为所有数据模型提供公共字段。

设计目的：
1. 减少重复代码：所有模型都需要 created_at 字段，统一写在这里。
2. 统一标准：强制所有时间使用 UTC 时区，防止服务器跨时区导致时间混乱。
3. 便于扩展：未来可以在此添加 updated_at、is_deleted 等通用字段。

继承关系：
    BaseModel (本模块)
        ├── User    (app.models.user)
        └── Session (app.models.session)

注意：SQLModel 的 table=True 模型和不带 table=True 的基类有不同的用途。
BaseModel 不设置 table=True，因此它只是一个 Mixin，不会单独创建数据库表。
"""

from datetime import datetime, UTC
from typing import List, Optional
from sqlmodel import Field, SQLModel, Relationship


class BaseModel(SQLModel):
    """
    所有数据模型的基类。

    每个继承此类的模型都会自动获得以下公共字段：
    - created_at: 记录创建时间（UTC 时区）。

    使用 lambda 工厂函数而非直接调用 datetime.now(UTC) 的好处：
        直接调用会在类定义时（模块导入时）固定时间值，
        而 lambda 工厂函数会在每次创建新实例时才生成时间。
    """

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
