#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一机器人接口
=============
定义机器人抽象基类 BaseBot 和工厂类 BotFactory，
为飞书、企业微信等不同平台提供统一的调用接口。
"""

from abc import ABC, abstractmethod
from typing import Optional


class BaseBot(ABC):
    """机器人抽象基类

    所有平台机器人适配器必须实现此接口，确保调用方可以
    以统一方式发送消息、处理事件和解析命令。
    """

    @abstractmethod
    def send_text(self, target_id: str, text: str) -> dict:
        """发送文本消息

        Args:
            target_id: 目标ID（群聊ID或用户ID）
            text: 文本内容

        Returns:
            dict: API 响应数据
        """
        ...

    @abstractmethod
    def send_file(self, target_id: str, file_path: str) -> dict:
        """发送文件消息

        Args:
            target_id: 目标ID（群聊ID或用户ID）
            file_path: 本地文件路径

        Returns:
            dict: API 响应数据
        """
        ...

    @abstractmethod
    def handle_event(self, event: dict) -> dict:
        """处理回调事件

        Args:
            event: 事件数据字典，包含消息内容、发送者等信息

        Returns:
            dict: 处理结果，包含 (reply_text, file_path_or_None)
        """
        ...

    @abstractmethod
    def parse_command(self, text: str) -> dict:
        """解析命令文本

        Args:
            text: 用户输入的消息文本

        Returns:
            dict: 包含 command 和 args 的字典
                - command: str, 命令类型
                - args: dict, 参数字典
        """
        ...


class BotFactory:
    """机器人工厂类

    根据平台名称创建对应的机器人实例。
    支持的平台: "feishu" -> FeishuBot, "wecom" -> WeComBot
    """

    @staticmethod
    def create_bot(platform: str) -> BaseBot:
        """创建指定平台的机器人实例

        Args:
            platform: 平台名称，支持 "feishu" 和 "wecom"

        Returns:
            BaseBot: 对应平台的机器人实例

        Raises:
            ValueError: 不支持的平台名称
        """
        platform = platform.strip().lower()

        if platform == "feishu":
            from core.feishu_bot import FeishuBot
            return FeishuBot()

        if platform == "wecom":
            from core.wecom_bot import WeComBot
            return WeComBot()

        raise ValueError(f"不支持的平台: {platform}，支持: feishu, wecom")


if __name__ == "__main__":
    print("统一机器人接口模块加载成功")

    # 测试工厂创建
    for p in ["feishu", "wecom"]:
        try:
            bot = BotFactory.create_bot(p)
            print(f"  {p} -> {bot.__class__.__name__} 创建成功")
        except Exception as e:
            print(f"  {p} -> 创建失败: {e}")

    # 测试不支持的平台
    try:
        BotFactory.create_bot("dingtalk")
    except ValueError as e:
        print(f"  不支持平台 -> 正确抛出异常: {e}")