import logging
import os
import sys
import time
from http import HTTPStatus

import requests
from dotenv import load_dotenv
from telebot import TeleBot

load_dotenv()


RESPONSE_NOT_DICT_ERROR = 'Ответ API должен быть словарем'
NO_HOMEWORKS_KEY_ERROR = 'В ответе API нет ключа "homeworks"'
HOMEWORKS_NOT_LIST_ERROR = 'Данные в "homeworks" должны быть списком'
NO_HOMEWORK_NAME_ERROR = 'Отсутствует ключ "homework_name" в ответе API'
NO_STATUS_ERROR = 'Отсутствует ключ "status" в ответе API'

MISSING_TOKENS = 'Отсутствуют обязательные переменные окружения: {tokens}'
API_REQUEST_ERROR = (
    'Ошибка при запросе к API: {error}. '
    'Параметры запроса: URL={url}, headers={headers}, params={params}'
)
SERVICE_UNAVAILABLE = (
    'Сервис недоступен (503) от {url}. '
    'Заголовки: {headers}, Параметры: {params}. '
    'Текст ответа: {response_text}...'
)
INVALID_STATUS_CODE = (
    'Неверный статус-код {code} от {url}. '
    'Заголовки: {headers}, Параметры: {params}. '
    'Текст ответа: {response_text}...'
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
API_REQUEST_START = 'Начинаем запрос к API: URL: {url}, Заголовки: {headers}'
NO_HOMEWORK_CHANGES = 'Нет изменений в статусе домашних работ.'
REQUEST_PARAMETERS = 'Параметры: {params}'
MESSAGE_SEND_ERROR = 'Ошибка при отправке сообщения об ошибке'
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


def check_tokens():
    """Проверяет доступность переменных окружения и вызывает исключение."""
    required_tokens = ['PRACTICUM_TOKEN', 'TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID']
    missing_tokens = [
    name for name in required_tokens 
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
        raise


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    request_info = {
        'url': ENDPOINT,
        'headers': HEADERS,
        'params': {'from_date': timestamp}
    }

    logging.debug(API_REQUEST_START.format(
        url=request_info['url'],
        headers=request_info['headers']
    ))

    try:
        response = requests.get(**request_info)
    except requests.RequestException as error:
        raise ConnectionError(
            API_REQUEST_ERROR.format(
                error=error,
                **request_info
            )
        )

    if response.status_code != HTTPStatus.OK:
        error_message = INVALID_STATUS_CODE.format(
            code=response.status_code,
            response_text=response.text[:200],
            **request_info
        )
        raise ConnectionError(error_message)

    api_data = response.json()

    for key in ('code', 'error'):
        if key in api_data:
            detail = f"{key}: {api_data.get(key)}"
            error_message = API_RETURNED_ERROR.format(
                url=request_info['url'],
                headers=request_info['headers'],
                details=detail
            )
            raise RuntimeError(error_message)

    return api_data


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    def raise_type_error(message, obj_type):
        raise TypeError(f'{message}. Получен тип: {obj_type.__name__}')

    if not isinstance(response, dict):
        raise_type_error(RESPONSE_NOT_DICT_ERROR, type(response))

    if 'homeworks' not in response:
        raise ValueError(NO_HOMEWORKS_KEY_ERROR)

    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise_type_error(HOMEWORKS_NOT_LIST_ERROR, type(homeworks))

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
                valid_statuses=', '.join(HOMEWORK_VERDICTS.keys())
            )
        )
    return STATUS_CHANGE.format(
        name=homework['homework_name'],
        verdict=HOMEWORK_VERDICTS[homework_status]
    )


def notify_error(bot, error_message):
    """Отправляет сообщение об ошибке и логирует ошибки."""
    try:
        bot.send_message(TELEGRAM_CHAT_ID, error_message)
    except Exception as send_error:
        logging.error(MESSAGE_SEND_ERROR_DETAIL.format(error=send_error))


def main():
    """Основная логика работы бота."""
    check_tokens()
    bot = TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time() - 2678400)
    last_msg = None

    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)
            if homeworks:
                message = parse_status(homeworks[0])
                send_message(bot, message)
                timestamp = response.get('current_date', timestamp)
        except Exception as e:
            error_message = BOT_ERROR_MESSAGE.format(error=e)
            logging.exception(error_message)
            if last_msg != error_message:
                notify_error(bot, error_message)
                last_msg = error_message
        finally:
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
