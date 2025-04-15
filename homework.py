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
    tokens = {
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }
    missing_tokens = [name for name, token in tokens.items() if not token]
    if missing_tokens:
        msg = MISSING_TOKENS.format(tokens=missing_tokens)
        logging.critical(msg)
        raise RuntimeError(msg)


def send_message(bot, message):
    """Отправляет сообщение в Telegram-чат."""
    logging.debug(f'Попытка отправки сообщения в Telegram: {message}')
    bot.send_message(TELEGRAM_CHAT_ID, message)
    logging.debug(MESSAGE_SENT_SUCCESS.format(message=message))
    return True


def get_api_answer(timestamp):
    """Делает запрос к единственному эндпоинту API-сервиса."""
    params = {'from_date': timestamp}
    request_info = {
        'url': ENDPOINT,
        'headers': HEADERS,
        'params': params
    }

    logging.debug(
        'Начинаем запрос к API: URL: {url}, Заголовки: {headers}'.format(
            url=request_info['url'], headers=request_info['headers']
        )
    )

    try:
        response = requests.get(**request_info)
    except requests.RequestException as error:
        error_message = API_REQUEST_ERROR.format(
            error=str(error),
            url=request_info['url'],
            headers=request_info['headers'],
            params=params
        )
        raise RuntimeError(error_message)

    if response.status_code != HTTPStatus.OK:
        error_message = INVALID_STATUS_CODE.format(
            code=response.status_code,
            url=ENDPOINT,
            headers=HEADERS,
            params=params,
            response_text=response.text[:200]
        )
        raise RuntimeError(error_message)

    api_data = response.json()

    if isinstance(api_data, dict):
        for word in ('code', 'error'):
            if word in api_data:
                error_details = {
                    'code': api_data.get('code'),
                    'error': api_data.get('error'),
                    'message': api_data.get('message', 'No message'),
                    'request_params': params,
                    'response': api_data
                }
                error_message = API_RETURNED_ERROR.format(
                    details=error_details,
                    url=ENDPOINT,
                    headers=HEADERS
                )
                raise RuntimeError(error_message)

    return api_data


def check_response(response):
    """Проверяет ответ API на соответствие документации."""
    if not isinstance(response, dict):
        raise TypeError(RESPONSE_NOT_DICT_ERROR)
    if 'homeworks' not in response:
        raise ValueError(NO_HOMEWORKS_KEY_ERROR)
    homeworks = response['homeworks']
    if not isinstance(homeworks, list):
        raise TypeError(HOMEWORKS_NOT_LIST_ERROR)
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


def log_no_homework_changes():
    """Логирует отсутствие изменений в статусе домашних работ."""
    logging.debug('Нет изменений в статусе домашних работ.')


def main():
    """Основная логика работы бота."""
    check_tokens()

    bot = TeleBot(TELEGRAM_TOKEN)
    timestamp = int(time.time() - 2678400)
    last_msg = None

    while True:
        try:
            params = {'from_date': timestamp}
            logging.debug('Параметры: {params}'.format(params=params))

            response = get_api_answer(timestamp)
            homeworks = check_response(response)

            if not homeworks:
                log_no_homework_changes()
                time.sleep(RETRY_PERIOD)
                continue

            message = parse_status(homeworks[0])
            if send_message(bot, message):
                timestamp = response.get('current_date', timestamp)

        except Exception as e:
            msg = f"Ошибка в процессе выполнения бота: {str(e)}"
            logging.exception(msg)
            if last_msg != msg:
                try:
                    send_message(bot, msg)
                except Exception:
                    logging.exception('Ошибка при отправке сообщения об ошибке')

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    log_file = __file__.replace('.py', '.log')

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file)
        ]
    )

    main()
