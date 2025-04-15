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


MISSING_TOKENS_MSG = 'Отсутствуют обязательные переменные окружения: {tokens}'
API_REQUEST_ERROR_MSG = (
    'Ошибка при запросе к API: {error}. '
    'Параметры запроса: URL={url}, headers={headers}, params={params}'
)
SERVICE_UNAVAILABLE_MSG = (
    'Сервис недоступен (503) от {url}. '
    'Заголовки: {headers}, Параметры: {params}. '
    'Текст ответа: {response_text}...'
)
INVALID_STATUS_CODE_MSG = (
    'Неверный статус-код {code} от {url}. '
    'Заголовки: {headers}, Параметры: {params}. '
    'Текст ответа: {response_text}...'
)
API_RETURNED_ERROR_MSG = (
    'API вернул ошибку: {details}. '
    'URL: {url}, Headers: {headers}'
)
STATUS_CHANGE_MSG = 'Изменился статус проверки работы "{name}". {verdict}'
INVALID_STATUS_MSG = (
    'Неизвестный статус домашней работы: "{status}". '
    'Допустимые статусы: {valid_statuses}'
)

PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
MONTH_TIMESTAMP = 2678400
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.',
}


def check_tokens():
    """Проверяет доступность переменных окружения и вызывает исключение."""
    tokens = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }
    missing_tokens = [name for name, token in tokens.items() if not token]
    if missing_tokens:
        msg = MISSING_TOKENS_MSG.format(tokens=missing_tokens)
        logging.critical(msg)
        raise exceptions.MissingTokenError(msg)


def send_message(bot, message):
    """Отправляет сообщение в Telegram-чат."""
    logging.debug(f'Попытка отправки сообщения в Telegram: {message}')
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logging.debug(f'Сообщение успешно отправлено в Telegram: {message}')
        return True
    except (telebot.apihelper.ApiException, requests.RequestException) as e:
        logging.exception(
            f'Ошибка при отправке сообщения "{message[:50]}...": {str(e)}'
        )
        return False


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    params = {'from_date': timestamp}
    request_info = {
        'url': ENDPOINT,
        'headers': HEADERS,
        'params': params
    }

    logging.debug(
        'Начинаем запрос к API: URL: {url}, Заголовки: {headers}, '
        'Параметры: {params}'.format(**request_info)
    )

    try:
        response = requests.get(**request_info)
    except requests.RequestException as error:
        error_message = API_REQUEST_ERROR_MSG.format(
            error=str(error),
            **request_info
        )
        logging.exception(error_message)
        raise exceptions.ApiResponseError(error_message)

    if response.status_code == HTTPStatus.SERVICE_UNAVAILABLE:
        error_message = SERVICE_UNAVAILABLE_MSG.format(
            url=ENDPOINT,
            headers=HEADERS,
            params=params,
            response_text=response.text[:200]
        )
        logging.error(error_message)
        raise exceptions.ApiResponseError(error_message)

    if response.status_code != HTTPStatus.OK:
        error_message = INVALID_STATUS_CODE_MSG.format(
            code=response.status_code,
            url=ENDPOINT,
            headers=HEADERS,
            params=params,
            response_text=response.text[:200]
        )
        logging.error(error_message)
        raise exceptions.ApiResponseError(error_message)

    api_data = response.json()

    if isinstance(api_data, dict) and (
            'code' in api_data or 'error' in api_data):
        error_details = {
            'code': api_data.get('code'),
            'error': api_data.get('error'),
            'message': api_data.get('message', 'No message'),
            'request_params': params,
            'response': api_data
        }
        error_message = API_RETURNED_ERROR_MSG.format(
            details=error_details,
            url=ENDPOINT,
            headers=HEADERS
        )
        logging.error(error_message)
        raise exceptions.ApiResponseError(error_message)

    return api_data


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    if not isinstance(response, dict):
        raise TypeError('Ответ API должен быть словарем')

    if 'homeworks' not in response:
        raise ValueError('В ответе API нет ключа "homeworks"')

    homeworkslist = response['homeworks']

    if not isinstance(homeworkslist, list):
        raise TypeError('Данные в "homeworks" должны быть списком')

    return homeworkslist


def parse_status(homework):
    """Извлекает статус конкретной домашней работы."""
    if 'homework_name' not in homework:
        raise KeyError('Отсутствует ключ "homework_name" в ответе API')

    if 'status' not in homework:
        raise KeyError('Отсутствует ключ "status" в ответе API')

    homework_status = homework['status']
    verdict = HOMEWORK_VERDICTS.get(homework_status)

    if verdict is None:
        raise ValueError(
            INVALID_STATUS_MSG.format(
                status=homework_status,
                valid_statuses=list(HOMEWORK_VERDICTS.keys())
            )
        )

    return STATUS_CHANGE_MSG.format(
        name=homework['homework_name'],
        verdict=verdict
    )


def main():
    """Основная логика работы бота."""
    check_tokens()

    bot = TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time() - MONTH_TIMESTAMP)
    last_msg = None

    while True:
        try:
            response = get_api_answer(timestamp)
            homeworks = check_response(response)

            if not homeworks:
                logging.debug('Нет изменений в статусе домашних работ.')
                time.sleep(RETRY_PERIOD)
                continue

            message = parse_status(homeworks[0])
            if send_message(bot, message):
                timestamp = response.get('current_date', timestamp)

        except Exception as e:
            msg = str(e)
            logging.error(msg)
            if last_msg != msg:
                send_message(bot, msg)
                last_msg = msg

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    log_file = os.path.join(os.path.dirname(os.path.abspath(
        __file__)), f"{os.path.basename(__file__)}.log")

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file)
        ]
    )

    main()
