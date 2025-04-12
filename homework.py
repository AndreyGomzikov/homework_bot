import logging
import os
import sys
import time
from http import HTTPStatus

import requests
import telebot
from dotenv import load_dotenv
from telebot import TeleBot

import exceptions


load_dotenv()


PRACTICUM_TOKEN = os.getenv("PRACTICUM_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RETRY_PERIOD = 600
MONTH_TIMESTAMP = 2678400
ENDPOINT = "https://practicum.yandex.ru/api/user_api/homework_statuses/"
HEADERS = {"Authorization": f"OAuth {PRACTICUM_TOKEN}"}


HOMEWORK_VERDICTS = {
    "approved": "Работа проверена: ревьюеру всё понравилось. Ура!",
    "reviewing": "Работа взята на проверку ревьюером.",
    "rejected": "Работа проверена: у ревьюера есть замечания.",
}


def check_tokens() -> list:
    """Проверяет доступность переменных окружения."""
    tokens = {
        "PRACTICUM_TOKEN": PRACTICUM_TOKEN,
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }
    missing_tokens = []
    for name, token in tokens.items():
        if not token:
            missing_tokens.append(name)
    return missing_tokens


def send_message(bot, message):
    """Отправляет сообщение в Telegram-чат."""
    logging.debug("Начинаем отправку сообщения в Telegram: %s", message)
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logging.debug("Сообщение успешно отправлено в Telegram: %s", message)
        return True
    except (telebot.apihelper.ApiException, requests.RequestException) as e:
        logging.error("Ошибка при отправке сообщения: %s", e)
        return False


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    params = {"from_date": timestamp}
    request_info = {"url": ENDPOINT, "headers": HEADERS, "params": params}

    logging.debug(
        "Начинаем запрос к API: URL: {url}, "
        "Заголовки: {headers}, Параметры: {params}".format(**request_info)
    )

    try:
        response = requests.get(**request_info)
    except requests.RequestException:
        msg = "Ошибка при запросе к API"
        raise exceptions.ApiResponseError(msg)

    if response.status_code != HTTPStatus.OK:
        msg = (
            f"Получен неверный статус-код {response.status_code} "
            f"от эндпоинта {ENDPOINT}."
        )
        raise exceptions.ApiResponseError(msg)

    try:
        return response.json()
    except ValueError:
        msg = "Ошибка преобразования к типам данных Python"
        raise exceptions.JsonDecodeError(msg)


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    if not isinstance(response, dict):
        msg = "Ответ API должен быть словарем"
        raise exceptions.CheckResponseException(msg)

    homeworks_list = response.get("homeworks")

    if homeworks_list is None:
        msg = "В ответе API нет словаря с домашками"
        raise exceptions.CheckResponseException(msg)

    if not isinstance(homeworks_list, list):
        msg = "В ответе API домашки представлены не списком"
        raise exceptions.CheckResponseException(msg)

    return homeworks_list


def parse_status(homework):
    """Извлекает статус конкретной домашней работы."""
    homework_name = homework.get("homework_name")
    if homework_name is None:
        msg = "Отсутствует ключ homework_name"
        raise KeyError(msg)

    homework_status = homework.get("status")
    if homework_status is None:
        msg = "Отсутствует ключ homework_name"
        raise KeyError(msg)

    verdict = HOMEWORK_VERDICTS.get(homework_status)
    if verdict is None:
        msg = "Неизвестный статус домашки"
        raise exceptions.HomeworkStatusErrorException(msg)

    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def handle_errors(e, last_msg, bot):
    """Обрабатывает ошибки и отправляет сообщения в Telegram."""
    msg = str(e)
    logging.error(msg)
    if last_msg != msg:
        send_message(bot, msg)
        last_msg = msg
    return last_msg


def main():
    """Основная логика работы бота."""
    missing_tokens = check_tokens()

    if missing_tokens:
        msg = 'Отсутствуют обязательные переменные окружения: {}'.format(
            ", ".join(missing_tokens)
        )
        logging.critical(msg)
        raise exceptions.MissingTokenError(msg)

    bot = TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time() - MONTH_TIMESTAMP)
    last_msg = None

    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if homeworks:
                hw = homeworks[0]
                status = parse_status(hw)
                if send_message(bot, status):
                    timestamp = response.get("current_date", timestamp)
            else:
                logging.debug("Нет изменений в статусе домашних работ.")

        except (exceptions.ApiResponseError,
                exceptions.JsonDecodeError,
                KeyError,
                exceptions.HomeworkStatusErrorException,
                exceptions.CheckResponseException) as e:
            last_msg = handle_errors(e, last_msg, bot)

        except Exception as e:
            last_msg = handle_errors(e, last_msg, bot)

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == "__main__":
    stream_handler = logging.StreamHandler(sys.stdout)
    file_handler = logging.FileHandler("bot.log")
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    )
    stream_handler.setFormatter(formatter)
    file_handler.setFormatter(formatter)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)

    main()
