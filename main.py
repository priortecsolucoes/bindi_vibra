"""Orquestrador do bot de coleta de pedidos do Canal de Negócios Vibra.
Pipeline FrameworkRE: INIT -> GET_DATA -> PROCESS -> END. Roda uma vez e encerra:
quem repete a execução é o cron do Railway."""

from Framework import EndModule, GetDataModule, InitModule, ProcessModule
from Framework.RPAFrameworkException import RPAFrameworkException
from Log.LogModule import LogModule
from Utils.AgentMonitor import monitored_run

AGENT_CODE = "vibra_monitor"
AGENT_NAME = "Vibra · monitoramento de pedidos"


def run() -> None:
    with monitored_run(AGENT_CODE, AGENT_NAME):
        _run_pipeline()


def _run_pipeline() -> None:
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


if __name__ == "__main__":
    run()
