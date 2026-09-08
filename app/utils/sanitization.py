"""
数据净化模块 - 提供输入数据的清洗和安全校验功能。

本模块提供了一系列安全相关的工具函数，用于防止常见的 Web 安全漏洞：

1. XSS (跨站脚本攻击) 防护：
   - HTML 实体转义（< → &lt;）。
   - 移除 <script> 标签。
   - 移除 null 字节。

2. SQL/命令注入防护：
   - 特殊字符清理。
   - 递归净化嵌套的数据结构。

3. 邮箱格式校验：
   - 正则验证标准邮箱格式。
   - 转换为小写统一存储。

4. 密码强度校验：
   - 长度、大小写字母、数字、特殊字符。
"""

import html
import re
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Union,
)


def sanitize_string(value: str) -> str:
    """
    净化字符串 - 防止 XSS 和注入攻击。

    处理步骤：
    1. 确保输入为字符串类型。
    2. HTML 实体转义（< → &lt;, > → &gt;, " → &quot; 等）。
    3. 移除 <script> 标签（即使被转义后也移除，双重保险）。
    4. 移除 null 字节 (\0)，防止字符串截断攻击。

    Args:
        value: 要净化的原始字符串。

    Returns:
        str: 净化后的安全字符串。

    示例：
        sanitize_string('<script>alert("xss")</script>')
        → ''  （script 标签被移除）
    """
    if not isinstance(value, str):
        value = str(value)

    # HTML 实体转义（防止 XSS）
    value = html.escape(value)

    # 移除被转义后的 script 标签（双重防护）
    value = re.sub(r"&lt;script.*?&gt;.*?&lt;/script&gt;", "", value, flags=re.DOTALL)

    # 移除 null 字节（防止字符串截断攻击）
    value = value.replace("\0", "")

    return value


def sanitize_email(email: str) -> str:
    """
    净化和校验邮箱地址。

    处理步骤：
    1. 基本字符串净化（XSS 防护）。
    2. 正则校验邮箱格式。
    3. 转换为小写（邮箱地址不区分大小写）。

    Args:
        email: 原始邮箱地址。

    Returns:
        str: 净化后的小写邮箱地址。

    Raises:
        ValueError: 邮箱格式不合法时抛出。

    示例：
        sanitize_email("User@Example.COM")
        → "user@example.com"
    """
    email = sanitize_string(email)

    # 标准邮箱格式校验
    if not re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email):
        raise ValueError("Invalid email format")

    return email.lower()


def sanitize_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    递归净化字典中的所有字符串值。

    遍历字典的所有键值对：
    - 字符串值 → sanitize_string。
    - 嵌套字典 → 递归调用 sanitize_dict。
    - 列表值 → 递归调用 sanitize_list。
    - 其他类型 → 保持不变。

    Args:
        data: 要净化的字典。

    Returns:
        Dict[str, Any]: 净化后的字典（新对象，不修改原对象）。

    示例：
        sanitize_dict({"name": "<script>xss</script>", "nested": {"key": "<b>bold</b>"}})
        → {"name": "", "nested": {"key": "&lt;b&gt;bold&lt;/b&gt;"}}
    """
    sanitized = {}
    for key, value in data.items():
        if isinstance(value, str):
            sanitized[key] = sanitize_string(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_dict(value)
        elif isinstance(value, list):
            sanitized[key] = sanitize_list(value)
        else:
            sanitized[key] = value
    return sanitized


def sanitize_list(data: List[Any]) -> List[Any]:
    """
    递归净化列表中的所有字符串值。

    遍历列表的所有元素：
    - 字符串元素 → sanitize_string。
    - 字典元素 → 递归调用 sanitize_dict。
    - 嵌套列表 → 递归调用 sanitize_list。
    - 其他类型 → 保持不变。

    Args:
        data: 要净化的列表。

    Returns:
        List[Any]: 净化后的列表（新对象，不修改原对象）。
    """
    sanitized = []
    for item in data:
        if isinstance(item, str):
            sanitized.append(sanitize_string(item))
        elif isinstance(item, dict):
            sanitized.append(sanitize_dict(item))
        elif isinstance(item, list):
            sanitized.append(sanitize_list(item))
        else:
            sanitized.append(item)
    return sanitized


def validate_password_strength(password: str) -> bool:
    """
    验证密码强度。

    强度要求（至少满足以下全部条件）：
    1. 长度 ≥ 8 个字符。
    2. 至少一个大写字母 (A-Z)。
    3. 至少一个小写字母 (a-z)。
    4. 至少一个数字 (0-9)。
    5. 至少一个特殊字符 (!@#$%^&*等)。

    Args:
        password: 要检查的明文密码。

    Returns:
        bool: True 表示密码强度合格。

    Raises:
        ValueError: 当密码不满足某条规则时抛出（附带具体原因）。
    """
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long")

    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")

    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")

    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one number")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        raise ValueError("Password must contain at least one special character")

    return True
