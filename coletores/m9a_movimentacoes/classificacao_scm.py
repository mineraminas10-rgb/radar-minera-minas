"""
Módulo 9A — classificação de tipos de evento do SCM a partir da
IDENTIDADE OFICIAL do evento (IDEvento + nome do dicionário `Evento.txt`),
nunca do texto narrativo livre (`OBEvento`/`DSPublicacaoDOU`).

ACHADO de 28/09/2026 que motivou este módulo: o classificador anterior
(em signals.py/db_writer.py, antes desta correção) comparava palavras-
chave direto contra o texto de cada ato, sem declarar qual campo do SCM
deveria alimentar essa comparação. Para o mesmo IDEvento=2325 ("AUT
PESQ/GUIA UTILIZAÇÃO PRORROGAÇÃO 03 ANOS PUBL", nome oficial e ESTÁVEL no
dicionário `Evento.txt` — o mesmo texto para qualquer processo que tiver
esse mesmo IDEvento), duas fontes de texto legítimas do mesmo ato batiam
diferente com a lista de palavras-chave:
  - `OBEvento` (narrativa livre, uma redação por ocorrência): "GUIA DE
    UTILIZAÇÃO" (com "de")
  - `DSEvento` (nome do dicionário, um só por IDEvento, reutilizado em
    todo processo que tiver esse tipo de evento): "GUIA UTILIZAÇÃO" (sem
    "de")

Conferi contra uma amostra real do dicionário inteiro (2.926 linhas de
`Evento.txt`, baixado em 28/09/2026) que isso NÃO é uma peculiaridade do
evento 2325: o mesmo dicionário tem, por exemplo, "PORTARIA CONCESSÃO DE
LAVRA" e "ALVARÁ DE PESQUISA" (com "de") ao lado de "GUIA UTILIZAÇÃO" (sem
"de") — a presença de preposição/artigo no nome oficial de cada tipo de
evento é inconsistente entre tipos, não previsível por regra fixa. Por
isso a correção não é adicionar mais uma variante textual a uma lista de
palavras-chave (isso só empurraria o mesmo bug pro próximo tipo de evento
não testado) — é normalizar removendo preposições/artigos ANTES de
comparar, e sempre comparar contra o nome do dicionário (estável), nunca
contra a narrativa (varia por redação).

Duas camadas, ambas gerais — nenhuma delas é uma regra para o evento 2325
especificamente:
  1. `normalizar_termo()`: minúsculas, sem acento, sem um conjunto pequeno
     de preposições/artigos curtos ("de", "da", "do", "das", "dos", "e",
     "em") — usado em QUALQUER comparação de palavra-chave deste pacote,
     tanto na lista de referência quanto no texto de entrada.
  2. `sufixo_situacao()`: o dicionário do SCM tem uma gramática de sufixo
     consistente em toda a amostra observada — termina em marcadores como
     PUBL/AUTORIZADO/APROVADO (concluído), PROTOC/REQUERIMENTO (em
     trâmite, ainda sem decisão), INDEFERIDA/CANCELADA/DEVOLVIDA/ANULADA
     (negativo). Usar esse sufixo para distinguir "autorização já
     concedida" de "mero requerimento" é genérico — vale para guia de
     utilização, portaria de lavra, alvará de pesquisa ou qualquer outro
     tipo do dicionário, não só para o par 2325/285 deste caso.

`_OVERRIDE_POR_ID_EVENTO` é um ponto de extensão para um IDEvento cuja
classificação a normalização por palavra-chave não capture bem — fica
VAZIO nesta entrega, de propósito: preenchê-lo com o IDEvento=2325 (ou
qualquer outro específico deste caso) seria exatamente o tipo de regra
pontual que este módulo foi desenhado para não precisar.
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

_STOPWORDS = {"de", "da", "do", "das", "dos", "e", "em"}

# Marcadores de sufixo observados na amostra real de Evento.txt (28/09/2026,
# 2.926 linhas) — não é uma lista fechada por desenho da ANM/SCM, é o que
# apareceu na amostra que consegui baixar; ajustar se uma amostra maior
# revelar outros marcadores.
_SUFIXOS_CONCLUIDO = {"publ", "autorizada", "autorizado", "deferida", "aprovado", "aprovada", "averbado", "averbada"}
_SUFIXOS_EM_TRAMITE = {"protoc", "requerimento", "aplicada"}
_SUFIXOS_NEGATIVO = {"indeferida", "cancelada", "devolvida", "negada", "anulada", "revogacao"}


def normalizar_termo(texto: Optional[str]) -> str:
    """Minúsculas, sem acento, sem pontuação, sem as stopwords curtas
    acima, espaço único. Usar SEMPRE antes de comparar palavra-chave
    contra texto do SCM — é a correção geral do achado deste módulo."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    palavras = [p for p in t.split() if p not in _STOPWORDS]
    return " ".join(palavras)


def contem_termo(texto_normalizado: str, *termos: str) -> bool:
    """`texto_normalizado` já deve ter passado por normalizar_termo(). Cada
    termo de referência em `termos` é normalizado aqui dentro — quem
    escreve a lista de palavras-chave não precisa se preocupar em já
    escrever sem preposição, a função cuida disso."""
    return any(normalizar_termo(t) in texto_normalizado for t in termos if t)


def sufixo_situacao(texto_normalizado: str) -> str:
    """'concluido' | 'em_tramite' | 'negativo' | 'indefinido', a partir dos
    marcadores de sufixo do próprio dicionário do SCM. Genérico: não
    depende de qual tipo de auto/guia/portaria é — só do marcador final.

    ACHADO ao testar contra a amostra real de Evento.txt: "PUBL" sozinho
    NÃO significa "autorizado" — o dicionário usa "PUBL" tanto para
    "AUTORIZADA PUBL" quanto para "INDEFERIDA PUBL" (a publicação no DOU é
    do ATO administrativo, que tanto pode ser conceder quanto negar). Por
    isso negativo/em_tramite são checados ANTES de concluido — "PUBL" só
    conta como conclusão positiva quando nenhum marcador negativo/de
    trâmite também está presente."""
    palavras = set(texto_normalizado.split())
    if palavras & _SUFIXOS_NEGATIVO:
        return "negativo"
    if palavras & _SUFIXOS_EM_TRAMITE:
        return "em_tramite"
    if palavras & _SUFIXOS_CONCLUIDO:
        return "concluido"
    return "indefinido"


@dataclass
class TipoEventoSCM:
    """Identidade oficial de um tipo de evento do SCM. Isto — nunca o
    texto narrativo (`OBEvento`/`DSPublicacaoDOU`) — deve alimentar
    classificação de sinais (signals.py) e de marco de timeline
    (db_writer.mapear_tipo_marco)."""
    id_tipo_evento: Optional[int]
    descricao_dicionario: str  # = Evento.txt.DSEvento, join por IDEvento

    @property
    def normalizado(self) -> str:
        return normalizar_termo(self.descricao_dicionario)

    @property
    def situacao(self) -> str:
        return sufixo_situacao(self.normalizado)

    def contem(self, *termos: str) -> bool:
        return contem_termo(self.normalizado, *termos)


_OVERRIDE_POR_ID_EVENTO: dict = {}  # deliberadamente vazio — ver docstring do módulo


def classificar(id_tipo_evento: Optional[int], descricao_dicionario: Optional[str]) -> TipoEventoSCM:
    if id_tipo_evento in _OVERRIDE_POR_ID_EVENTO:
        return _OVERRIDE_POR_ID_EVENTO[id_tipo_evento]
    return TipoEventoSCM(id_tipo_evento=id_tipo_evento, descricao_dicionario=descricao_dicionario or "")
