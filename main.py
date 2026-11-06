"""Orquestrador do bot de coleta de pedidos do Canal de Negócios Vibra.
Pipeline FrameworkRE: INIT -> GET_DATA -> PROCESS -> END, repetido a cada
SCHEDULE_INTERVAL_MINUTES (0 = roda uma vez só, como no cron do Railway)."""

import os
import sys
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

from Framework import EndModule, GetDataModule, InitModule, ProcessModule
from Framework.RPAFrameworkException import RPAFrameworkException
from Log.LogModule import LogModule

DEFAULT_INTERVAL_MINUTES = 5


def run() -> None:
    log_module = None
    try:
        config = InitModule.initialize()
        pending_items = GetDataModule.get_data(config)
        log_module = LogModule()
        ProcessModule.process_items(pending_items, config, log_module)
    except RPAFrameworkException as exc:
        print(f"[ERRO Framework] {exc}")
    finally:
        EndModule.finalize(log_module)


def _read_interval_minutes() -> float:
    raw_value = os.environ.get("SCHEDULE_INTERVAL_MINUTES", "").strip() or str(DEFAULT_INTERVAL_MINUTES)
    try:
        interval = float(raw_value.replace(",", "."))
    except ValueError:
        interval = -1
    if interval < 0:
        print(f"[ERRO Framework] SCHEDULE_INTERVAL_MINUTES deve ser um número >= 0; valor recebido: {raw_value!r}")
        sys.exit(1)
    return interval


def run_scheduled() -> None:
    load_dotenv()
    interval_minutes = _read_interval_minutes()
    if interval_minutes == 0:
        run()
        return

    print(f"[INFO] Agendamento ativo: execução a cada {interval_minutes:g} minuto(s). Ctrl+C para parar.")
    try:
        while True:
            started_at = datetime.now()
            print("=" * 55)
            print(f"[INFO] Início da execução: {started_at:%d/%m/%Y %H:%M:%S}")
            try:
                run()
            except Exception as exc:  # noqa: BLE001 - erro inesperado numa execução não pode parar o agendamento
                print(f"[ERRO] Execução interrompida por erro inesperado: {exc!r}")

            # Intervalo contado a partir do início: execução mais longa que o intervalo emenda na próxima.
            next_run = started_at + timedelta(minutes=interval_minutes)
            wait_seconds = (next_run - datetime.now()).total_seconds()
            if wait_seconds > 0:
                print(f"[INFO] Próxima execução: {next_run:%d/%m/%Y %H:%M:%S}")
                time.sleep(wait_seconds)
            else:
                print("[AVISO] A execução demorou mais que o intervalo - iniciando a próxima imediatamente.")
    except KeyboardInterrupt:
        print("[INFO] Agendamento encerrado pelo usuário.")


if __name__ == "__main__":
    run_scheduled()
