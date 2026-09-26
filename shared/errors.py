"""自定义异常体系（design.md §6.1）。"""


class DailyReportError(Exception):
    """本项目所有业务异常的共同父类。"""


class ConfigError(DailyReportError):
    """配置缺失、类型错误或环境变量未注入。"""


class CollectorError(DailyReportError):
    """采集层失败（网络、限流、响应结构异常）。"""


class GeneratorError(DailyReportError):
    """生成层失败（数据无法聚合、模板渲染异常）。"""


class NotifierError(DailyReportError):
    """推送层失败（SMTP 或飞书机器人返回错误）。"""
