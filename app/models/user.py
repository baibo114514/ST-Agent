"""
用户模型 - 定义用户(User)的数据库表结构。

本模块定义了 User 类，对应数据库中的 "user" 表：
- 存储用户邮箱（唯一索引）和 bcrypt 哈希密码。
- 提供密码哈希和验证方法。
- 与 Session 模型建立一对多关系。

安全设计：
    - 密码永不存储明文：使用 bcrypt 哈希 + 随机盐值。
    - 相同密码不同用户得到不同哈希值（盐值随机）。
    - verify_password 使用恒定时间比较，防止时序攻击。

表名：user

关系说明：
    User (1) ──── (N) Session
    一个用户可以有多个聊天会话。

循环导入处理：
    使用 TYPE_CHECKING 和文件末尾延迟导入避免循环依赖。
"""

from typing import (
    TYPE_CHECKING,
    List,
)

import bcrypt  # bcrypt 密码哈希库
from sqlmodel import (
    Field,
    Relationship,
)

from app.models.base import BaseModel

# 仅在类型检查时导入 Session，避免运行时循环导入
if TYPE_CHECKING:
    from app.models.session import Session


class User(BaseModel, table=True):
    """
    用户表模型。

    属性说明：
        id: 自增主键，用户唯一标识。
        email: 用户邮箱地址，建立唯一索引（不允许重复注册）。
        hashed_password: 经过 bcrypt 哈希后的密码字符串（绝不为明文）。
        created_at: 账户创建时间（UTC，继承自 BaseModel）。
        sessions: 该用户拥有的所有聊天会话（一对多关系）。
    """

    __tablename__ = "user"

    id: int = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str  # bcrypt 哈希值（含盐值），非明文密码

    # 一对多关系：user.sessions 返回该用户的所有 Session 对象
    # back_populates="user" 对应 Session 模型中的 user 属性
    sessions: List["Session"] = Relationship(back_populates="user")

    def verify_password(self, password: str) -> bool:
        """
        验证用户输入的明文密码是否与存储的 bcrypt 哈希值匹配。

        使用 bcrypt.checkpw 进行比较：
        - 自动从哈希值中提取盐值。
        - 使用恒定时间比较（防止时序攻击）。
        - 相同密码因盐值不同会产生不同哈希值。

        Args:
            password: 用户输入的明文密码。

        Returns:
            bool: True 表示密码正确，False 表示密码错误。
        """
        return bcrypt.checkpw(
            password.encode("utf-8"),
            self.hashed_password.encode("utf-8")
        )

    @staticmethod
    def hash_password(password: str) -> str:
        """
        使用 bcrypt 对明文密码进行哈希加密。

        处理流程：
        1. bcrypt.gensalt() 生成随机盐值（增加哈希强度，防止彩虹表攻击）。
        2. bcrypt.hashpw() 使用盐值对密码进行哈希。
        3. 将二进制结果解码为 UTF-8 字符串以便存储。

        注意：每次 gensalt() 生成不同的随机盐值，
        因此即使两个用户设置相同密码，最终存储的哈希值也完全不同。

        Args:
            password: 明文密码。

        Returns:
            str: bcrypt 哈希后的密码字符串（可直接存入数据库）。
        """
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(
            password.encode("utf-8"),
            salt
        ).decode("utf-8")


# 文件末尾延迟导入，避免循环依赖
# noqa: E402 告诉 flake8 忽略此行（因为正常的 import 应该在文件顶部）
from app.models.session import Session  # noqa: E402
