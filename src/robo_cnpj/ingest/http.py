"""Download com retomada e descompactação — usado por todos os ingestores."""

from __future__ import annotations

import time
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypeVar

import httpx
from rich.console import Console
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn

console = Console()

# dadosabertos.rfb.gov.br é notoriamente instável: fica fora do ar por minutos a
# horas sob demanda alta, sem aviso. Timeout de conexão maior porque o servidor
# demora a responder mesmo quando está de pé; o retry existe para o resto.
TIMEOUT = httpx.Timeout(60.0, read=300.0)
CABECALHOS = {"User-Agent": "robo-cnpj/0.1 (prospeccao contabil)"}

ERROS_DE_CONEXAO = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)

TENTATIVAS_MAX = 25
ESPERA_INICIAL_S = 30.0
ESPERA_MAXIMA_S = 300.0
# Com esses valores, o teto de espera antes de desistir de um arquivo é de
# ~1h50 (30+60+120+240 + 20×300s) — dá margem para os apagões mais comuns
# desse servidor sem travar o processo indefinidamente.

T = TypeVar("T")


class ConexaoIndisponivelError(RuntimeError):
    """Esgotadas as tentativas de conexão — o servidor remoto está fora do ar."""


def repetir_com_backoff(operacao: Callable[[], T], rotulo: str) -> T:
    """Repete `operacao` com espera crescente entre falhas de conexão.

    Martelar reconexões não ajuda contra um servidor sobrecarregado — esperar
    mais a cada tentativa (30s, 60s, 120s... até 5min) é o que de fato dá
    chance do servidor se recuperar. Erros que não são de conectividade (404,
    layout inesperado etc.) sobem na hora, sem retry.
    """
    espera = ESPERA_INICIAL_S
    for tentativa in range(1, TENTATIVAS_MAX + 1):
        try:
            return operacao()
        except ERROS_DE_CONEXAO as erro:
            if tentativa == TENTATIVAS_MAX:
                raise ConexaoIndisponivelError(
                    f"{rotulo}: sem conexão após {TENTATIVAS_MAX} tentativas "
                    f"({type(erro).__name__}). O servidor pode estar fora do ar — "
                    "tente novamente mais tarde; o que já baixou fica em cache."
                ) from erro
            console.print(
                f"  [yellow]{rotulo}: falha de conexão (tentativa {tentativa}/"
                f"{TENTATIVAS_MAX}, {type(erro).__name__}). "
                f"Nova tentativa em {espera:.0f}s...[/]"
            )
            time.sleep(espera)
            espera = min(espera * 2, ESPERA_MAXIMA_S)

    raise AssertionError("inalcançável")  # o raise dentro do loop sempre dispara antes


def _zip_valido(caminho: Path) -> bool:
    """Um download interrompido no meio pode deixar um .zip corrompido em cache.

    Sem checar isto, uma execução anterior que falhou parcialmente faria as
    execuções seguintes confiarem num arquivo quebrado para sempre — silencioso.
    """
    try:
        return zipfile.is_zipfile(caminho)
    except OSError:
        return False


def baixar(url: str, destino: Path, forcar: bool = False) -> Path:
    """Baixa `url` para `destino`, retomando de onde parou e tentando de novo
    em queda de conexão. Uma vez completo, o arquivo nunca é buscado de novo —
    só chamado outra vez com `forcar=True`.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    parcial = destino.with_suffix(destino.suffix + ".parcial")

    if destino.exists() and not forcar:
        if destino.suffix.lower() != ".zip" or _zip_valido(destino):
            return destino
        console.print(f"  [yellow]{destino.name}: cache corrompido, baixando de novo[/]")
        destino.unlink()

    def _tentativa() -> Path:
        ja_baixado = parcial.stat().st_size if parcial.exists() else 0
        cabecalhos = dict(CABECALHOS)
        if ja_baixado:
            cabecalhos["Range"] = f"bytes={ja_baixado}-"

        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as cliente:
            with cliente.stream("GET", url, headers=cabecalhos) as resposta:
                # 206 = servidor aceitou retomar; 200 com Range enviado = ignorou, recomeça.
                if ja_baixado and resposta.status_code == 200:
                    ja_baixado_local = 0
                else:
                    ja_baixado_local = ja_baixado
                    if resposta.status_code not in (200, 206):
                        resposta.raise_for_status()

                total = int(resposta.headers.get("content-length", 0)) + ja_baixado_local
                modo = "ab" if ja_baixado_local else "wb"

                with Progress(
                    TextColumn("[cyan]{task.description}"),
                    BarColumn(),
                    DownloadColumn(),
                    TransferSpeedColumn(),
                ) as barra:
                    tarefa = barra.add_task(destino.name, total=total or None,
                                            completed=ja_baixado_local)
                    with parcial.open(modo) as fh:
                        for bloco in resposta.iter_bytes(chunk_size=1 << 20):
                            fh.write(bloco)
                            barra.update(tarefa, advance=len(bloco))

        parcial.replace(destino)
        return destino

    return repetir_com_backoff(_tentativa, destino.name)


def extrair(zip_path: Path, destino: Path, sufixo: str | None = None) -> Iterator[Path]:
    """Extrai membros do ZIP e devolve os caminhos.

    `sufixo` filtra por final do nome (case-insensitive). A Receita nomeia o
    conteúdo com sufixos próprios (.EMPRECSV, .ESTABELE) em vez de .csv.
    """
    destino.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        for membro in zf.namelist():
            if membro.endswith("/"):
                continue
            if sufixo and not membro.upper().endswith(sufixo.upper()):
                continue

            saida = destino / Path(membro).name
            if not saida.exists():
                with zf.open(membro) as origem, saida.open("wb") as fh:
                    while bloco := origem.read(1 << 20):
                        fh.write(bloco)
            yield saida
