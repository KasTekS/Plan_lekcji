# Plan_lekcji/email_utils.py
# Nowy plik - funkcje wysyłania emaili

from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils.html import strip_tags


def send_verification_code(user, code, request=None):
    """Wysyła kod weryfikacyjny na email użytkownika"""

    # Przygotowanie kontekstu dla szablonu
    context = {
        'user': user,
        'code': code.code,
        'expires_minutes': 10,
        'ip_address': get_client_ip(request) if request else 'Nieznane',
    }

    # Renderowanie szablonu HTML
    html_message = render_to_string('emails/verification_code.html', context)
    plain_message = strip_tags(html_message)

    subject = f'Kod weryfikacyjny do logowania - AWANS'

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Błąd wysyłania emaila: {e}")
        return False


def send_password_reset_code(user, code, request=None):
    """Wysyła kod do resetu hasła"""

    context = {
        'user': user,
        'code': code.code,
        'expires_minutes': 15,
        'ip_address': get_client_ip(request) if request else 'Nieznane',
    }

    html_message = render_to_string('emails/password_reset_code.html', context)
    plain_message = strip_tags(html_message)

    subject = f'Reset hasła - AWANS'

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Błąd wysyłania emaila: {e}")
        return False


def send_trusted_device_notification(user, device_name, request=None):
    """Wysyła powiadomienie o dodaniu nowego zaufanego urządzenia"""

    context = {
        'user': user,
        'device_name': device_name,
        'ip_address': get_client_ip(request) if request else 'Nieznane',
    }

    html_message = render_to_string('emails/trusted_device_added.html', context)
    plain_message = strip_tags(html_message)

    subject = f'Dodano nowe zaufane urządzenie - AWANS'

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        return True
    except Exception as e:
        print(f"Błąd wysyłania emaila: {e}")
        return False


def get_client_ip(request):
    """Pobiera adres IP klienta z requestu"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_device_name(request):
    """Generuje nazwę urządzenia na podstawie User-Agent"""
    user_agent = request.META.get('HTTP_USER_AGENT', '')

    # Prosta detekcja przeglądarki i systemu
    browser = 'Nieznana przeglądarka'
    system = 'Nieznany system'

    if 'Chrome' in user_agent and 'Edg' not in user_agent:
        browser = 'Chrome'
    elif 'Firefox' in user_agent:
        browser = 'Firefox'
    elif 'Safari' in user_agent and 'Chrome' not in user_agent:
        browser = 'Safari'
    elif 'Edg' in user_agent:
        browser = 'Edge'

    if 'Windows' in user_agent:
        system = 'Windows'
    elif 'Mac' in user_agent:
        system = 'macOS'
    elif 'Linux' in user_agent:
        system = 'Linux'
    elif 'Android' in user_agent:
        system = 'Android'
    elif 'iPhone' in user_agent or 'iPad' in user_agent:
        system = 'iOS'

    return f"{browser} na {system}"