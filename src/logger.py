import logging
from logging.handlers import TimedRotatingFileHandler


def create_logger():

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # 创建TimedRotatingFileHandler处理程序
    handler = TimedRotatingFileHandler('./logs/app.log', when='midnight', interval=1, backupCount=7)
    handler.suffix = '%Y-%m-%d'
    handler.setLevel(logging.INFO)

    # 创建日志记录格式
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
    handler.setFormatter(formatter)

    # 将处理程序添加到记录器
    logger.addHandler(handler)

    return logger

logger = create_logger()