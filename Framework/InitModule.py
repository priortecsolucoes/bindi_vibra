"""INIT — valida variáveis de ambiente, credenciais e pré-requisitos.
Nunca abre navegador nem lê dados de negócio aqui."""

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

from Framework.RPAFrameworkException import RPAFrameworkException
from Utils.DriverFactory import resolve_chrome_binary
from Utils.TokenApiClient import check_health

DEFAULT_TOKEN_API_URL = "https://emailtokenreader.up.railway.app"


@dataclass
class BotConfig:
    headless: bool
    chrome_binary_path: Optional[str]
    chrome_user_data_dir: Optional[str]
    chrome_profile_directory: Optional[str]
    chrome_user_agent: Optional[str]
    chrome_window_size: Optional[str]
    orders_path: Optional[str]
    mfa_wait_seconds: int
    default_username: Optional[str]
    default_password: Optional[str]
    token_api_url: Optional[str]
    token_api_token: Optional[str]
    token_timeout_seconds: int
    portal_api_url: str
    portal_api_token: str
    portal_pending_days: int


def initialize() -> BotConfig:
    """Carrega o .env e valida os pré-requisitos mínimos para a execução."""
    load_dotenv()

    orders_path = os.environ.get("PEDIDOS_PATH", "").strip() or None
    if orders_path and not os.path.isfile(orders_path):
        raise RPAFrameworkException(
            f"PEDIDOS_PATH está definido ({orders_path}) mas o arquivo não existe."
        )

    portal_api_url = os.environ.get("PORTAL_API_URL", "").strip()
    portal_api_token = os.environ.get("PORTAL_API_TOKEN", "").strip()
    if not portal_api_url or not portal_api_token:
        raise RPAFrameworkException(
            "Defina PORTAL_API_URL e PORTAL_API_TOKEN no .env - são obrigatórios para buscar "
            "os pedidos pendentes e reportar a situação dos itens ao Portal Bindi Log."
        )
    raw_pending_days = os.environ.get("PORTAL_PENDING_DAYS", "").strip() or "3"
    if not raw_pending_days.isdigit():
        raise RPAFrameworkException(
            f"PORTAL_PENDING_DAYS deve ser um inteiro não negativo; valor recebido: {raw_pending_days!r}"
        )
    portal_pending_days = int(raw_pending_days)

    raw_mfa_wait = os.environ.get("MFA_WAIT_SECONDS", "").strip() or "180"
    try:
        mfa_wait_seconds = int(raw_mfa_wait)
    except ValueError as exc:
        raise RPAFrameworkException(
            f"MFA_WAIT_SECONDS deve ser um número inteiro; valor recebido: {raw_mfa_wait!r}"
        ) from exc

    # Login padrão na Vibra: vale para as unidades sem usuário/senha no cadastro do portal.
    default_username = os.environ.get("VIBRA_USUARIO", "").strip() or None
    default_password = os.environ.get("VIBRA_SENHA", "").strip() or None

    # Vibra Token API (projeto Bindi-Email): lê no Gmail o código de 2FA. Sem ela
    # (ou se o código não chegar), vale o token informado na tela de Unidades do portal.
    # VIBRA_TOKEN_API_URL=0 desliga a API.
    raw_token_api_url = os.environ.get("VIBRA_TOKEN_API_URL", "").strip() or DEFAULT_TOKEN_API_URL
    token_api_url = None if raw_token_api_url == "0" else raw_token_api_url
    token_api_token = os.environ.get("VIBRA_TOKEN_API_TOKEN", "").strip() or None
    if token_api_url and not token_api_token:
        raise RPAFrameworkException(
            f"Defina VIBRA_TOKEN_API_TOKEN no .env (mesmo valor da variável API_TOKEN do serviço "
            f"bindi_email_token_reader no Railway) para ler o código de 2FA em {token_api_url}. "
            "Para usar só o token informado no portal, use VIBRA_TOKEN_API_URL=0."
        )
    raw_token_timeout = os.environ.get("TOKEN_TIMEOUT_S", "").strip() or "120"
    if not raw_token_timeout.isdigit() or int(raw_token_timeout) < 1:
        raise RPAFrameworkException(
            f"TOKEN_TIMEOUT_S deve ser um inteiro positivo; valor recebido: {raw_token_timeout!r}"
        )
    token_timeout_seconds = int(raw_token_timeout)
    if token_api_url:
        check_health(token_api_url)
        print(f"[OK] Vibra Token API disponível ({token_api_url}) - o código de 2FA será lido do e-mail.")
    else:
        print("[AVISO] VIBRA_TOKEN_API_URL=0 - o código de 2FA virá só do token informado no portal.")

    headless = os.environ.get("CHROME_HEADLESS", "").strip() in ("1", "true", "True")
    # Perfil persistente próprio do bot: guarda os cookies do SSO da Vibra entre
    # execuções, senão o código de 2FA é pedido a cada execução (perfil temporário).
    chrome_user_data_dir = os.path.abspath(os.environ.get("CHROME_USER_DATA_DIR") or "chrome_profile")
    chrome_profile_directory = os.environ.get("CHROME_PROFILE_DIRECTORY") or None
    # Deixe CHROME_USER_AGENT vazio no .env por padrão - ver o motivo em
    # Utils/DriverFactory.create_driver (mismatch com os Client Hints).
    chrome_user_agent = os.environ.get("CHROME_USER_AGENT") or None
    chrome_window_size = os.environ.get("CHROME_WINDOW_SIZE") or None

    # Só valida se CHROME_BINARY_PATH foi definido explicitamente; senão o
    # próprio ChromeDriver localiza o Chrome instalado.
    chrome_binary_path = resolve_chrome_binary(os.environ.get("CHROME_BINARY_PATH") or None)

    print("[OK] Ambiente validado (.env, credenciais e pré-requisitos).")

    return BotConfig(
        headless=headless,
        chrome_binary_path=chrome_binary_path,
        chrome_user_data_dir=chrome_user_data_dir,
        chrome_profile_directory=chrome_profile_directory,
        chrome_user_agent=chrome_user_agent,
        chrome_window_size=chrome_window_size,
        orders_path=orders_path,
        mfa_wait_seconds=mfa_wait_seconds,
        default_username=default_username,
        default_password=default_password,
        token_api_url=token_api_url,
        token_api_token=token_api_token,
        token_timeout_seconds=token_timeout_seconds,
        portal_api_url=portal_api_url,
        portal_api_token=portal_api_token,
        portal_pending_days=portal_pending_days,
    )

