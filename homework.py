import logging
import os
import sys
import time
from http import HTTPStatus

import requests
from dotenv import load_dotenv
from telebot import TeleBot

load_dotenv()


RESPONSE_TYPE_ERROR = ('Ответ API должен быть словарем. '
                      'Получен тип: {type_name}')
NO_HOMEWORKS_KEY_ERROR = 'В ответе API нет ключа "homeworks"'
HOMEWORKS_TYPE_ERROR = ('Данные в "homeworks" должны быть списком. '
                       'Получен тип: {type_name}')
NO_HOMEWORK_NAME_ERROR = 'Отсутствует ключ "homework_name" в ответе API'
NO_STATUS_ERROR = 'Отсутствует ключ "status" в ответе API'
MISSING_TOKENS = 'Отсутствуют обязательные переменные окружения: {tokens}'
API_REQUEST_ERROR = (
    'Ошибка при запросе к API: {error}. '
    'Параметры запроса: URL={url}, заголовки={headers}, параметры={params}'
)
INVALID_STATUS_CODE = (
    'Неверный статус-код {code} от {url}. '
    'Заголовки: {headers}, Параметры: {params}.'
)
API_RETURNED_ERROR = (
    'API вернул ошибку: {details}. '
    'URL: {url}, Headers: {headers}'
)
STATUS_CHANGE = 'Изменился статус проверки работы "{name}". {verdict}'
INVALID_STATUS = (
    'Неизвестный статус домашней работы: "{status}". '
    'Допустимые статусы: {valid_statuses}'
)
MESSAGE_SENT_SUCCESS = 'Сообщение успешно отправлено в Telegram: {message}'
MESSAGE_SEND_ERROR_DETAIL = 'Ошибка отправки сообщения в Telegram: {error}'
SEND_MESSAGE_ATTEMPT = 'Попытка отправки сообщения в Telegram: {message}'
API_REQUEST_START = (
    'Начинаем запрос к API: URL: {url}, '
    'Заголовки: {headers}, Параметры: {params}'
)
NO_HOMEWORK_CHANGES = 'Нет изменений в статусе домашних работ.'
BOT_ERROR_MESSAGE = 'Ошибка в процессе выполнения бота: {error}'

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.',
}

REQUIRED_TOKENS = ['PRACTICUM_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID']


def check_tokens():
    """Проверяет доступность переменных окружения и вызывает исключение."""
    missing_tokens = [
        name for name in REQUIRED_TOKENS
        if not globals().get(name)
    ]
    if missing_tokens:
        message = MISSING_TOKENS.format(tokens=missing_tokens)
        logging.critical(message)
        raise RuntimeError(message)


def send_message(bot, message):
    """Отправляет сообщение в Telegram-чат."""
    logging.debug(SEND_MESSAGE_ATTEMPT.format(message=message))
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logging.debug(MESSAGE_SENT_SUCCESS.format(message=message))
    except Exception as error:
        logging.error(MESSAGE_SEND_ERROR_DETAIL.format(error=error))
        return False
    return True


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    params = {'from_date': timestamp}
    logging.debug(
        API_REQUEST_START.format(url=ENDPOINT, headers=HEADERS, params=params)
    )

    try:
        response = requests.get(ENDPOINT, headers=HEADERS, params=params)
        logging.debug(f'Ответ API: {response.text}')
    except requests.RequestException as error:
        raise ConnectionError(
            API_REQUEST_ERROR.format(
                error=error,
                url=ENDPOINT,
                headers=HEADERS,
                params=params
            )
        )

    if response.status_code != HTTPStatus.OK:
        error_message = INVALID_STATUS_CODE.format(
            code=response.status_code,
            url=ENDPOINT,
            headers=HEADERS,
            params=params,
        )
        raise RuntimeError(error_message)

    api_data = response.json()
    logging.debug(f"Ответ API как JSON: {api_data}")

    for key in ('code', 'error'):
        if key in api_data:
            error_message = API_RETURNED_ERROR.format(
                details=api_data.get(key),
                url=ENDPOINT,
                headers=HEADERS
            )
            raise RuntimeError(error_message)

    logging.debug(f"Все параметры запроса: {params}")

    return api_data


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    if not isinstance(response, dict):
        raise TypeError(
            RESPONSE_TYPE_ERROR.format(type_name=type(response).__name__)
        )

    if 'homeworks' not in response:
        raise ValueError(NO_HOMEWORKS_KEY_ERROR)

    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(
            HOMEWORKS_TYPE_ERROR.format(type_name=type(homeworks).__name__)
        )

    return homeworks


def parse_status(homework):
    """Извлекает статус конкретной домашней работы."""
    if 'homework_name' not in homework:
        raise KeyError(NO_HOMEWORK_NAME_ERROR)
    if 'status' not in homework:
        raise KeyError(NO_STATUS_ERROR)
    homework_status = homework['status']
    if homework_status not in HOMEWORK_VERDICTS:
        raise ValueError(
            INVALID_STATUS.format(
                status=homework_status,
            )
        )
    return STATUS_CHANGE.format(
        name=homework['homework_name'],
        verdict=HOMEWORK_VERDICTS[homework_status]
    )


def main():
    """Основная логика работы бота."""
    check_tokens()
    bot = TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time() - 2678400)
    last_error_message = None

    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if homeworks:
                message = parse_status(homeworks[0])
                if send_message(bot, message):
                    timestamp = response.get('current_date', timestamp)
                else:
                    logging.warning(
                        "Ошибка отправки сообщения, "
                        "повторная попытка через 10 минут."
                    )

            else:
                logging.info(NO_HOMEWORK_CHANGES)
        except Exception as e:
            error_message = BOT_ERROR_MESSAGE.format(error=e)
            if error_message != last_error_message:
                logging.exception(error_message)
                send_message(bot, error_message)
                last_error_message = error_message
        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(__file__.replace('.py', '.log'))
        ]
    )

    main()
