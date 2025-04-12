class ApiResponseError():
    """Исключение для ошибок, связанных с ответом API."""


class JsonDecodeError():
    """Исключение для ошибок декодирования JSON."""


class CheckResponseException():
    """Исключение, возникающее при проверке ответа API."""


class HomeworkStatusErrorException():
    """Исключение при неизвестном статусе домашней работы."""


class MissingTokenError(Exception):
    """Исключение для отсутствия обязательных токенов."""
