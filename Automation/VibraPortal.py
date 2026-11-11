"""Passos de automação do Canal de Negócios Vibra (cn.vibraenergia.com.br) via Selenium.

Seletores confirmados via inspeção real do DOM (login SSO Keycloak +
aplicação Angular Material), exceto onde indicado o contrário.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, List, Optional

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from Utils.TokenApiClient import fetch_token, prepare_token

# 'Meus pedidos' não abre mais por URL direta: entra pela home e segue o menu
# lateral Pedidos > Consultar > Pedidos Enviados.
HOME_URL = "https://cn.vibraenergia.com.br/home/#/"
ORDERS_MENU_PATH = ("Pedidos", "Consultar", "Pedidos Enviados")

DEFAULT_TIMEOUT = 30
MFA_POLL_SECONDS = 5

POPUP_WAIT_SECONDS = 10

# Menu lateral (Angular): recolhido mostra só ícones; os títulos (span.titulo) só
# ficam visíveis com o menu expandido.
MENU_SELECTOR = "app-menu-item"
MENU_ITEM_XPATH = (
    "//app-menu-item//div[contains(@class,'main-item')]"
    "[.//span[contains(@class,'titulo')][normalize-space()='{title}']]"
)
# Empresa (posto) ativa no cabeçalho e diálogo "Outras empresas do grupo": um
# mesmo login enxerga vários postos, mas 'Meus pedidos' só lista os do posto ativo.
CURRENT_COMPANY_SELECTOR = "div.dados-cliente span.nome"
COMPANY_SWITCH_TRIGGER_SELECTOR = "i.trigger-grupo-empresa"
COMPANY_OPTION_SELECTOR = "div.grupo-empresa"
COMPANY_OPTION_NAME_SELECTOR = "div.razao-social span"
COMPANY_FOOTER_BUTTON_XPATH = "//div[contains(@class,'footer-grupo-empresa')]//button[normalize-space()='{text}']"
COMPANY_SWITCH_TIMEOUT = 60

# Popup "Informativos" que a home abre por cima de tudo após o login.
POPUP_CLOSE_XPATH = "//app-informativo-lateral//i[contains(@class,'md-icons')][normalize-space()='close']"

# Lista 'Meus pedidos': abre filtrada pelos últimos 30 dias (chip "Cadastrado em ...")
# e paginada de 10 em 10 - o bot remove o filtro e passa para 100 por página.
FILTER_CHIP_SELECTOR = "app-meus-pedidos mat-chip"
FILTER_CHIP_REMOVE_SELECTOR = "app-meus-pedidos mat-chip button.mat-mdc-chip-remove"
PAGE_SIZE_SELECT_SELECTOR = "mat-paginator mat-select"
PAGE_SIZE_VALUE_SELECTOR = "mat-paginator .mat-mdc-select-value-text"
PAGE_SIZE_OPTION_XPATH = "//mat-option[normalize-space()='{size}']"
PAGINATOR_RANGE_SELECTOR = "mat-paginator .mat-mdc-paginator-range-label"
ORDERS_PAGE_SIZE = "100"
LIST_REFRESH_SECONDS = 15

ORDER_NUMBER_SELECTOR = "td.mat-column-numeroPedido span.numero-pedido-selecionado"
PRODUCT_ROWS_SELECTOR = "app-lista-produtos table.tabela-lista-produtos tbody tr"

# Ícones Material exibidos à esquerda de cada produto no detalhe do pedido.
APPROVED_ICON_TEXT = "delete"
BLOCKED_ICON_TEXT = "do_disturb_alt"
STATUS_ICON_TEXTS = {APPROVED_ICON_TEXT, BLOCKED_ICON_TEXT}
ORDER_ICONS_TIMEOUT = 60

# Status geral do pedido no detalhe ('Status' > badge div.alert com ícone 'info' + texto).
ORDER_STATUS_XPATH = (
    "//li[contains(@class,'detalhes-title')][normalize-space()='Status']"
    "/following-sibling::li[contains(@class,'detalhes-subtitle')]//div[contains(@class,'alert')]"
)
# Pedido já em carregamento: a Vibra não mostra os ícones de aprovado/bloqueado,
# mas todos os produtos estão autorizados.
PROGRAMMED_STATUS_TEXT = "Totalmente Programado"
# Pedido já faturado: também sem ícones; reportado ao portal como 'faturado'.
INVOICED_STATUS_TEXT = "Totalmente Faturado"


@dataclass
class OrderItem:
    """Um produto de um pedido, como aparece na tela de detalhe."""

    order_number: str
    order_status: str
    product_name: str
    product_code: str
    base: str
    quantity_liters: float
    pending_quantity_liters: float
    approved: bool


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------
def login(
    driver: webdriver.Chrome,
    username: str,
    password: str,
    mfa_wait_seconds: int,
    fetch_mfa_code: Callable[[], Optional[str]],
    token_api_url: Optional[str] = None,
    token_api_token: Optional[str] = None,
    token_timeout_seconds: int = 120,
    timeout: int = DEFAULT_TIMEOUT,
) -> None:
    """Abre a home (redireciona pro SSO), autentica e espera o menu lateral carregar.
    Se o SSO pedir o código de 2FA (enviado por e-mail), lê o código na Vibra
    Token API (projeto Bindi-Email) quando token_api_url estiver definido. Sem a
    API, ou se o código não chegar/não for aceito, consulta fetch_mfa_code (token
    informado na tela de Unidades do Portal Bindi Log) por até mfa_wait_seconds."""
    print("[INFO] Acessando o Canal de Negócios Vibra...")
    driver.get(HOME_URL)

    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, MENU_SELECTOR) or d.find_elements(By.ID, "username")
        )
    except TimeoutException as exc:
        raise RuntimeError(
            f"Nem a tela de login nem a home do portal apareceram a tempo. URL atual: {driver.current_url}"
        ) from exc

    if driver.find_elements(By.CSS_SELECTOR, MENU_SELECTOR):
        print("[OK] Sessão do SSO reaproveitada do perfil do bot - login não foi necessário.")
        return

    # O ticket precisa ser emitido antes de enviar a senha, senão o e-mail do
    # código pode chegar antes e ser descartado como antigo.
    ticket: Optional[int] = None
    if token_api_url:
        try:
            ticket = prepare_token(token_api_url, token_api_token)
        except Exception as exc:  # noqa: BLE001 - sem a API ainda resta o token informado no portal
            print(f"[AVISO] Falha ao preparar a leitura do código no e-mail: {exc}")
            token_api_url = None

    username_field = driver.find_element(By.ID, "username")
    username_field.clear()
    username_field.send_keys(username)
    password_field = driver.find_element(By.ID, "password")
    password_field.clear()
    password_field.send_keys(password)
    driver.find_element(By.ID, "loginBt").click()

    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, MENU_SELECTOR) or _is_mfa_screen(d)
        )
    except TimeoutException as exc:
        raise RuntimeError(
            "Login não confirmado: a home do portal não carregou. "
            f"Verifique usuário/senha. URL atual: {driver.current_url}"
        ) from exc

    if _is_mfa_screen(driver):
        if token_api_url and _submit_mfa_code_from_email(
            driver, token_api_url, token_api_token, ticket, token_timeout_seconds, timeout
        ):
            print("[OK] Login realizado com sucesso (código de 2FA lido do e-mail).")
            return
        print(
            "[AVISO] Autenticação em 2 fatores: informe o código recebido por e-mail no campo "
            f"'Token Login Dist.' da unidade, na tela de Unidades do portal. Aguardando até {mfa_wait_seconds}s..."
        )
        typed_codes: List[str] = []
        try:
            WebDriverWait(driver, mfa_wait_seconds, poll_frequency=MFA_POLL_SECONDS).until(
                lambda d: _try_mfa_code(d, fetch_mfa_code, typed_codes)
                or d.find_elements(By.CSS_SELECTOR, MENU_SELECTOR)
            )
        except TimeoutException as exc:
            detail = "código informado não foi aceito" if typed_codes else "código não informado no portal"
            raise RuntimeError(f"Autenticação em 2 fatores não concluída em {mfa_wait_seconds}s ({detail}).") from exc

    print("[OK] Login realizado com sucesso.")


def _submit_mfa_code_from_email(
    driver: webdriver.Chrome,
    token_api_url: str,
    token_api_token: Optional[str],
    ticket: Optional[int],
    token_timeout_seconds: int,
    timeout: int,
) -> bool:
    """Busca o código na Vibra Token API e o envia. Devolve False (para cair no
    token informado no portal) se o código não chegar ou não for aceito."""
    print(f"[INFO] Autenticação em 2 fatores: aguardando o código no e-mail (Vibra Token API, até {token_timeout_seconds}s)...")
    try:
        code = fetch_token(token_api_url, token_api_token, ticket, token_timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - sem o e-mail ainda resta o token informado no portal
        print(f"[AVISO] {exc} Passando para o token informado no portal.")
        return False

    print(f"[OK] Código de 2FA recebido do e-mail: {code}")
    if not _submit_mfa_code(driver, code):
        return False
    try:
        WebDriverWait(driver, timeout).until(lambda d: d.find_elements(By.CSS_SELECTOR, MENU_SELECTOR))
    except TimeoutException:
        if not _is_mfa_screen(driver):
            raise RuntimeError(
                f"Código de 2FA aceito, mas a home do portal não carregou. URL atual: {driver.current_url}"
            ) from None
        print(f"[AVISO] Código de 2FA {code} não foi aceito. Passando para o token informado no portal.")
        return False
    return True


def _try_mfa_code(driver: webdriver.Chrome, fetch_mfa_code: Callable[[], Optional[str]], typed_codes: List[str]) -> bool:
    """Digita na tela de 2FA um código novo vindo do portal. Sempre devolve
    False - quem encerra a espera é a home do portal carregando."""
    if not _is_mfa_screen(driver):
        return False
    try:
        code = fetch_mfa_code()
    except Exception as exc:  # noqa: BLE001 - falha momentânea do portal não pode abortar a espera
        print(f"[AVISO] Falha ao consultar o token no portal (tentando de novo): {exc}")
        return False
    if not code or code in typed_codes:
        return False

    if _submit_mfa_code(driver, code):
        typed_codes.append(code)
        print("[INFO] Token informado no portal digitado na tela de 2FA.")
    return False


def _submit_mfa_code(driver: webdriver.Chrome, code: str) -> bool:
    # Seletor do campo de código não confirmado via DOM - usa o primeiro input visível da tela.
    inputs = [
        field for field in driver.find_elements(By.CSS_SELECTOR, "form input:not([type=hidden])")
        if field.is_displayed() and field.is_enabled()
    ]
    if not inputs:
        print("[ERRO] Campo do código de 2FA não encontrado na tela.")
        return False
    inputs[0].clear()
    inputs[0].send_keys(code, Keys.ENTER)
    return True


def _is_mfa_screen(driver: webdriver.Chrome) -> bool:
    return "Autenticação em 2 fatores" in driver.find_element(By.TAG_NAME, "body").text


def _wait_orders_list(driver: webdriver.Chrome, timeout: int) -> None:
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR))
    )


# --------------------------------------------------------------------------
# Lista 'Meus pedidos'
# --------------------------------------------------------------------------
def list_order_numbers(driver: webdriver.Chrome) -> List[str]:
    """Números de pedido da página atual da lista (sem filtro de data, 100 por
    página - ver _prepare_orders_list)."""
    spans = driver.find_elements(By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR)
    order_numbers = [span.text.strip() for span in spans if span.text.strip()]
    # Deduplica mantendo a ordem da tela.
    return list(dict.fromkeys(order_numbers))


def open_order_detail(driver: webdriver.Chrome, order_number: str, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Clica no número do pedido na lista 'Meus pedidos' (a lista precisa estar aberta)."""
    link = WebDriverWait(driver, timeout).until(
        EC.element_to_be_clickable(
            (
                By.XPATH,
                "//span[contains(@class,'numero-pedido-selecionado') "
                f"and normalize-space()='{order_number}']",
            )
        )
    )
    # Clique via JS: o clique nativo é interceptado por células vizinhas da linha (layout responsivo).
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", link)

    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, PRODUCT_ROWS_SELECTOR))
        )
    except TimeoutException as exc:
        raise RuntimeError(
            f"Detalhe do pedido {order_number} não carregou a lista de produtos."
        ) from exc


def _all_status_icons_loaded(driver: webdriver.Chrome) -> bool:
    try:
        product_rows = [
            row for row in driver.find_elements(By.CSS_SELECTOR, PRODUCT_ROWS_SELECTOR)
            if row.find_elements(By.CSS_SELECTOR, "div.title-produto")
        ]
        return bool(product_rows) and all(_status_icon_texts(row) & STATUS_ICON_TEXTS for row in product_rows)
    except StaleElementReferenceException:
        return False


def _status_icon_texts(row) -> set:
    return {
        (icon.get_attribute("textContent") or "").strip()
        for icon in row.find_elements(By.CSS_SELECTOR, "div.nome-imagem-codigo i")
    }


def back_to_orders_list(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> None:
    """O detalhe abre dentro da própria aplicação: voltar no histórico costuma
    bastar; se a lista não reaparecer, refaz o caminho pela home."""
    driver.back()
    try:
        _wait_orders_list(driver, timeout)
    except TimeoutException:
        print("[AVISO] Lista 'Meus pedidos' não reapareceu ao voltar - reabrindo pelo menu.")
        driver.get(HOME_URL)
        open_orders_list(driver, timeout)
        return
    # A lista pode voltar com o filtro de data e 10 por página de novo.
    _prepare_orders_list(driver, timeout)


# --------------------------------------------------------------------------
# Troca de empresa (posto) do grupo
# --------------------------------------------------------------------------
def go_home(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Volta à home e fecha o popup 'Informativos', que reabre a cada visita."""
    driver.get(HOME_URL)
    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.CSS_SELECTOR, MENU_SELECTOR)))
    except TimeoutException as exc:
        raise RuntimeError(f"Home do portal não carregou em {timeout}s. URL atual: {driver.current_url}") from exc
    _close_informative_popup(driver)


def read_current_company(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> str:
    try:
        element = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CURRENT_COMPANY_SELECTOR))
        )
    except TimeoutException as exc:
        raise RuntimeError("Nome da empresa ativa não encontrado no cabeçalho do portal.") from exc
    # textContent: o nome aparece truncado ("...") na tela, mas o texto completo está no DOM.
    return (element.get_attribute("textContent") or "").strip()


def switch_to_next_company(driver: webdriver.Chrome, visited: List[str], timeout: int = DEFAULT_TIMEOUT) -> Optional[str]:
    """Abre 'Outras empresas do grupo' (precisa estar na home, sem o popup) e
    troca para a primeira empresa ainda não visitada. Devolve o nome dela, ou
    None (diálogo cancelado) se todas já foram visitadas."""
    trigger = _wait_clickable(driver, By.CSS_SELECTOR, COMPANY_SWITCH_TRIGGER_SELECTOR, timeout, "seta de troca de empresa")
    _safe_click(driver, trigger)
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: [o for o in d.find_elements(By.CSS_SELECTOR, COMPANY_OPTION_SELECTOR) if o.is_displayed()]
        )
    except TimeoutException as exc:
        raise RuntimeError("Diálogo 'Outras empresas do grupo' não abriu após clicar na seta.") from exc

    visited_keys = {name.strip().upper() for name in visited}
    target_name = None
    for option in driver.find_elements(By.CSS_SELECTOR, COMPANY_OPTION_SELECTOR):
        names = option.find_elements(By.CSS_SELECTOR, COMPANY_OPTION_NAME_SELECTOR)
        name = (names[0].get_attribute("textContent") or "").strip() if names else ""
        if not name or name.upper() in visited_keys:
            continue
        radio = option.find_element(By.CSS_SELECTOR, "input[type=radio]")
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", radio)
        target_name = name
        break

    if target_name is None:
        _safe_click(driver, _wait_clickable(
            driver, By.XPATH, COMPANY_FOOTER_BUTTON_XPATH.format(text="Cancelar"), timeout, "botão Cancelar"
        ))
        return None

    print(f"[INFO] Trocando para a empresa {target_name}...")
    _safe_click(driver, _wait_clickable(
        driver, By.XPATH, COMPANY_FOOTER_BUTTON_XPATH.format(text="Trocar"), timeout, "botão Trocar"
    ))
    try:
        WebDriverWait(driver, COMPANY_SWITCH_TIMEOUT).until(
            lambda d: _current_company_or_empty(d).upper() == target_name.upper()
        )
    except TimeoutException as exc:
        raise RuntimeError(
            f"Troca para a empresa {target_name} não confirmada em {COMPANY_SWITCH_TIMEOUT}s "
            f"(cabeçalho mostra '{_current_company_or_empty(driver)}')."
        ) from exc
    return target_name


def _current_company_or_empty(driver: webdriver.Chrome) -> str:
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, CURRENT_COMPANY_SELECTOR)
        return (elements[0].get_attribute("textContent") or "").strip() if elements else ""
    except StaleElementReferenceException:
        return ""


def _wait_clickable(driver: webdriver.Chrome, by: str, selector: str, timeout: int, label: str):
    try:
        return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector)))
    except TimeoutException as exc:
        raise RuntimeError(f"Elemento '{label}' não ficou clicável em {timeout}s ({selector}).") from exc


def _safe_click(driver: webdriver.Chrome, element) -> None:
    try:
        element.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)


# --------------------------------------------------------------------------
# Home > menu lateral > Pedidos Enviados
# --------------------------------------------------------------------------
def open_orders_list(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Parte da home (logo após o login): fecha o popup 'Informativos', expande
    o menu lateral e segue Pedidos > Consultar > Pedidos Enviados até a lista carregar."""
    _close_informative_popup(driver)

    print(f"[INFO] Menu > {' > '.join(ORDERS_MENU_PATH)}")
    _expand_side_menu(driver, ORDERS_MENU_PATH[0], timeout)
    for title, next_title in zip(ORDERS_MENU_PATH, ORDERS_MENU_PATH[1:]):
        _open_menu_group(driver, title, next_title, timeout)
    _hover_click(driver, _find_visible_menu_entry(driver, ORDERS_MENU_PATH[-1], timeout))

    try:
        _wait_orders_list(driver, timeout)
    except TimeoutException as exc:
        raise RuntimeError(
            f"Lista 'Pedidos Enviados' não carregou em {timeout}s após o clique no menu. URL atual: {driver.current_url}"
        ) from exc
    _prepare_orders_list(driver, timeout)


def _prepare_orders_list(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Atualiza o filtro de data até hoje e mostra 100 pedidos por página -
    senão o pedido pode ficar fora do período ou numa página seguinte. Só age
    no que ainda não estiver ajustado."""
    _update_date_filter_to_today(driver, timeout)

    if _current_page_size(driver) != ORDERS_PAGE_SIZE:
        _refresh_list_with(driver, lambda: _choose_page_size(driver, timeout), timeout)
        try:
            WebDriverWait(driver, timeout).until(lambda d: _current_page_size(d) == ORDERS_PAGE_SIZE)
        except TimeoutException as exc:
            raise RuntimeError(
                f"'Itens por página' não mudou para {ORDERS_PAGE_SIZE} (está em '{_current_page_size(driver)}')."
            ) from exc
        print(f"[INFO] Lista com {ORDERS_PAGE_SIZE} itens por página.")

    page_range = _text_or_empty(driver, PAGINATOR_RANGE_SELECTOR)
    total_pages = re.search(r"de\s+(\d+)", page_range)
    if total_pages and int(total_pages.group(1)) > 1:
        print(
            f"[AVISO] A lista tem mais de uma página mesmo com {ORDERS_PAGE_SIZE} por página ({page_range}) - "
            "só a primeira é verificada."
        )


def _update_date_filter_to_today(driver: webdriver.Chrome, timeout: int) -> None:
    """A lista abre com o chip 'Cadastrado em X até Y' terminando numa data
    antiga. O X do chip não remove o filtro: troca o período para terminar hoje.
    Por isso só clica se a data final ainda não for hoje (evita clicar de novo
    ao voltar do detalhe)."""
    chip_text = _text_or_empty(driver, FILTER_CHIP_SELECTOR)
    if not chip_text:
        return
    end_date = re.search(r"até\s+(\d{2}/\d{2}/\d{4})", chip_text)
    if not end_date:
        print(f"[AVISO] Filtro de data da lista com formato inesperado ('{chip_text}') - mantido como está.")
        return
    today = date.today().strftime("%d/%m/%Y")
    if end_date.group(1) == today:
        return

    remove_button = _wait_clickable(driver, By.CSS_SELECTOR, FILTER_CHIP_REMOVE_SELECTOR, timeout, "X do filtro de data")
    _refresh_list_with(driver, lambda: _safe_click(driver, remove_button), timeout)
    try:
        WebDriverWait(driver, timeout).until(lambda d: _text_or_empty(d, FILTER_CHIP_SELECTOR) != chip_text)
    except TimeoutException as exc:
        raise RuntimeError(
            f"Filtro de data da lista 'Meus pedidos' não mudou após clicar no X (continua '{chip_text}')."
        ) from exc
    # O textContent do chip inclui o nome do ícone do X ('cancel').
    new_text = re.sub(r"\s*cancel\s*$", "", _text_or_empty(driver, FILTER_CHIP_SELECTOR)) or "removido"
    print(f"[INFO] Filtro de data atualizado: {new_text}.")


def _choose_page_size(driver: webdriver.Chrome, timeout: int) -> None:
    _safe_click(driver, _wait_clickable(driver, By.CSS_SELECTOR, PAGE_SIZE_SELECT_SELECTOR, timeout, "Itens por página"))
    option = _wait_clickable(
        driver, By.XPATH, PAGE_SIZE_OPTION_XPATH.format(size=ORDERS_PAGE_SIZE), timeout, f"opção {ORDERS_PAGE_SIZE}"
    )
    _safe_click(driver, option)


def _refresh_list_with(driver: webdriver.Chrome, action, timeout: int) -> None:
    """Executa a ação e espera a tabela ser redesenhada - sem isso a leitura
    pegaria as linhas antigas, de antes do filtro/paginação mudar."""
    old_rows = driver.find_elements(By.CSS_SELECTOR, ORDER_NUMBER_SELECTOR)
    action()
    if old_rows:
        try:
            WebDriverWait(driver, LIST_REFRESH_SECONDS).until(EC.staleness_of(old_rows[0]))
        except TimeoutException:
            pass  # o Angular pode reaproveitar as linhas; a espera abaixo garante a lista na tela
    try:
        _wait_orders_list(driver, timeout)
    except TimeoutException as exc:
        raise RuntimeError(f"Lista 'Meus pedidos' não recarregou em {timeout}s.") from exc


def _current_page_size(driver: webdriver.Chrome) -> str:
    return _text_or_empty(driver, PAGE_SIZE_VALUE_SELECTOR)


def _text_or_empty(driver: webdriver.Chrome, selector: str) -> str:
    try:
        elements = driver.find_elements(By.CSS_SELECTOR, selector)
        return (elements[0].get_attribute("textContent") or "").strip() if elements else ""
    except StaleElementReferenceException:
        return ""


def _close_informative_popup(driver: webdriver.Chrome) -> None:
    """O popup aparece alguns segundos depois da home e bloqueia o menu. Sem
    informativo pendente ele não aparece - aí só segue."""
    try:
        close_icon = WebDriverWait(driver, POPUP_WAIT_SECONDS, poll_frequency=0.5).until(
            lambda d: _first_visible(d, POPUP_CLOSE_XPATH)
        )
    except TimeoutException:
        return
    try:
        close_icon.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", close_icon)
    try:
        WebDriverWait(driver, DEFAULT_TIMEOUT).until(lambda d: not _first_visible(d, POPUP_CLOSE_XPATH))
    except TimeoutException as exc:
        raise RuntimeError("Popup 'Informativos' da home não fechou após clicar no X.") from exc
    print("[INFO] Popup 'Informativos' fechado.")


def _expand_side_menu(driver: webdriver.Chrome, first_title: str, timeout: int) -> None:
    """Põe o mouse sobre o menu lateral recolhido para ele expandir e mostrar os títulos."""
    title_xpath = MENU_ITEM_XPATH.format(title=first_title)
    if _wait_visible(driver, title_xpath, 0):
        return
    try:
        icon = WebDriverWait(driver, timeout).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, f"{MENU_SELECTOR} div.main-item"))
        )
    except TimeoutException as exc:
        raise RuntimeError(f"Menu lateral não apareceu em {timeout}s. URL atual: {driver.current_url}") from exc

    ActionChains(driver).move_to_element(icon).perform()
    if _wait_visible(driver, title_xpath, 5):
        return
    # Hover real às vezes não chega ao Angular (janela sem foco/headless): dispara os eventos via JS.
    driver.execute_script(
        "for (var el = arguments[0]; el; el = el.parentElement) {"
        "  ['mouseenter', 'mouseover'].forEach(function (t) {"
        "    el.dispatchEvent(new MouseEvent(t, {bubbles: t === 'mouseover', view: window}));"
        "  });"
        "}",
        icon,
    )
    if not _wait_visible(driver, title_xpath, 5):
        raise RuntimeError(f"Menu lateral não expandiu: título '{first_title}' não apareceu.")


def _open_menu_group(driver: webdriver.Chrome, title: str, next_title: str, timeout: int) -> None:
    """Se o subitem já estiver visível, o grupo já está aberto - clicar de novo o recolheria."""
    next_xpath = MENU_ITEM_XPATH.format(title=next_title)
    if _wait_visible(driver, next_xpath, 1):
        return
    _hover_click(driver, _find_visible_menu_entry(driver, title, timeout))
    # O subitem abre com animação (expandCollapse: altura 0 -> auto).
    if not _wait_visible(driver, next_xpath, timeout // 3):
        raise RuntimeError(f"Menu '{title}' foi clicado mas o subitem '{next_title}' não apareceu.")


def _find_visible_menu_entry(driver: webdriver.Chrome, title: str, timeout: int):
    try:
        return WebDriverWait(driver, timeout).until(lambda d: _first_visible(d, MENU_ITEM_XPATH.format(title=title)))
    except TimeoutException as exc:
        raise RuntimeError(f"Item '{title}' do menu lateral não ficou visível em {timeout}s.") from exc


def _hover_click(driver: webdriver.Chrome, element) -> None:
    # Clica com o mouse "andando" até o item, para o menu não recolher no caminho.
    try:
        ActionChains(driver).move_to_element(element).click().perform()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", element)


def _wait_visible(driver: webdriver.Chrome, xpath: str, timeout: float) -> bool:
    if timeout <= 0:
        return bool(_first_visible(driver, xpath))
    try:
        WebDriverWait(driver, timeout, poll_frequency=0.25).until(lambda d: _first_visible(d, xpath))
        return True
    except TimeoutException:
        return False


def _first_visible(driver: webdriver.Chrome, xpath: str):
    for element in driver.find_elements(By.XPATH, xpath):
        try:
            if element.is_displayed() and element.size["height"] > 0:
                return element
        except StaleElementReferenceException:
            continue
    return False


# --------------------------------------------------------------------------
# Detalhe do pedido
# --------------------------------------------------------------------------
def extract_order_items(driver: webdriver.Chrome, order_number: str) -> List[OrderItem]:
    """Lê os produtos do detalhe do pedido.

    Colunas: [Produto(s), Base, Prazo, Qtd (L), Qtd pendente (L),
    Preço unitário, Valor total]. Ícone de lixeira = aprovado; ícone de
    bloqueio = não aprovado (a linha bloqueada também traz a lixeira,
    desabilitada - por isso o bloqueio é checado primeiro).
    """
    order_status = _read_order_status(driver, order_number)
    is_programmed = order_status.lower() in (PROGRAMMED_STATUS_TEXT.lower(), INVOICED_STATUS_TEXT.lower())
    if is_programmed:
        print(f"[INFO] Pedido {order_number}: {order_status} - produtos considerados aprovados (sem ícones de situação).")
    else:
        # Os ícones de situação (aprovado/bloqueado) carregam depois das linhas.
        try:
            WebDriverWait(driver, ORDER_ICONS_TIMEOUT, poll_frequency=0.5).until(_all_status_icons_loaded)
        except TimeoutException:
            print(
                f"[AVISO] Pedido {order_number} (status '{order_status}'): ícones de situação não carregaram "
                f"em {ORDER_ICONS_TIMEOUT}s - lendo assim mesmo."
            )

    items: List[OrderItem] = []
    for row in driver.find_elements(By.CSS_SELECTOR, PRODUCT_ROWS_SELECTOR):
        title = row.find_elements(By.CSS_SELECTOR, "div.title-produto")
        if not title:
            continue

        cells = row.find_elements(By.XPATH, "./td")
        if len(cells) < 5:
            raise RuntimeError(
                f"Pedido {order_number}: linha de produto com {len(cells)} coluna(s), esperado ao menos 5."
            )

        product_name = title[0].find_element(By.TAG_NAME, "strong").text.strip()
        product_code = (
            title[0].find_element(By.CSS_SELECTOR, "span.codigo-produto").text.replace("COD:", "").strip()
        )

        items.append(
            OrderItem(
                order_number=order_number,
                order_status=order_status,
                product_name=product_name,
                product_code=product_code,
                base=cells[1].text.strip(),
                quantity_liters=_parse_liters(cells[3].text),
                pending_quantity_liters=_parse_liters(cells[4].text),
                approved=True if is_programmed else _is_approved(row, order_number, product_name),
            )
        )

    if not items:
        raise RuntimeError(f"Pedido {order_number}: nenhum produto encontrado na tela de detalhe.")
    return items


def _is_approved(row, order_number: str, product_name: str) -> bool:
    icon_texts = sorted(_status_icon_texts(row))
    if BLOCKED_ICON_TEXT in icon_texts:
        return False
    if APPROVED_ICON_TEXT in icon_texts:
        return True
    raise RuntimeError(
        f"Pedido {order_number}/{product_name}: ícone de situação não reconhecido ({icon_texts})."
    )


def _read_order_status(driver: webdriver.Chrome, order_number: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Status geral do pedido (ex.: 'Totalmente Programado', 'Parcialmente Bloqueado')."""
    try:
        badge = WebDriverWait(driver, timeout).until(
            lambda d: _first_with_text(d.find_elements(By.XPATH, ORDER_STATUS_XPATH))
        )
    except TimeoutException:
        print(f"[AVISO] Pedido {order_number}: Status do pedido não encontrado no detalhe em {timeout}s.")
        return ""
    # O textContent do badge começa com o nome do ícone Material ('info').
    icon_text = "".join((i.get_attribute("textContent") or "") for i in badge.find_elements(By.TAG_NAME, "i"))
    full_text = (badge.get_attribute("textContent") or "").strip()
    if icon_text and full_text.startswith(icon_text.strip()):
        full_text = full_text[len(icon_text.strip()):]
    return " ".join(full_text.split())


def _first_with_text(elements):
    for element in elements:
        try:
            if (element.get_attribute("textContent") or "").strip():
                return element
        except StaleElementReferenceException:
            continue
    return False


def _parse_liters(raw: str) -> float:
    """'10.000' ou '3.000,50' (pt-BR) -> float."""
    cleaned = raw.strip().replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError as exc:
        raise RuntimeError(f"Quantidade (L) inválida na tela de detalhe: {raw!r}") from exc


def is_invoiced_status(order_status: str) -> bool:
    return order_status.strip().lower() == INVOICED_STATUS_TEXT.lower()
