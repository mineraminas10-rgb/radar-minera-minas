"""
Módulo 9A — unidade editorial e deduplicação (Carta M9A §5).

Regras (literal da carta):
  1. Identificar o evento pela combinação processo, descrição normalizada,
     texto da publicação e data.
  2. Bloquear republicação literal do mesmo ato, mesmo com nova data de
     carregamento.
  3. Agrupar atos idênticos da mesma empresa, data, substância e geografia
     quando formarem uma decisão editorial única.
  4. Agrupar atos complementares da mesma família (ex.: instauração de
     decaimento + intimação para defesa).
  4b. (Adição de 28/09/2026 — achado da auditoria do caso 830.649/2020)
     Agrupar também atos que, mesmo em datas/famílias-de-palavra-chave
     diferentes, se referem ao MESMO instrumento administrativo (mesmo
     número de guia/portaria/alvará, extraído do texto do ato) — ex.:
     emissão da Guia de Utilização nº 61/2023 (2023) e prorrogação da
     mesma Guia nº 61/2023 (2026) são atos DISTINTOS da MESMA sequência
     processual, e devem cair no mesmo caso editorial (mesmo evento,
     dois marcos na timeline), sem se fundir num só fato. Ver
     `extrair_identificador_instrumento()` abaixo — é genérico (usa um
     regex sobre o padrão "Nº NNN/AAAA" que a ANM usa para qualquer
     guia/portaria/alvará), não específico a este processo nem a este
     par de atos.
  5. Manter os atos individuais na Timeline_Processual, mas contar apenas
     um caso em Editorial.
  6. Criar nova versão quando houver alteração material (titular, situação,
     decisão, área, substância, prazo ou efeito).

Esta lógica de chaves é pura (não depende de rede) e por isso é a parte
mais confiável do coletor M9A — testada em test_consolidacao.py com dados
sintéticos que reproduzem os 5 casos de controle da carta (§11), sem
precisar da amostra real do SCM.

ACHADO de 28/09/2026: a normalização de texto usada para regra 1/3/4
(`normalizar_descricao` abaixo) passou a rodar sobre `ato.descricao`, que
agora é o nome do dicionário `Evento.txt` (DSEvento, estável por
IDEvento) — não mais texto narrativo livre (isso se move para
`ato.texto_narrativo`, novo campo). Ver classificacao_scm.py para o
raciocínio completo dessa separação.
"""
import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional

import classificacao_scm as clsf


def normalizar_descricao(texto: str) -> str:
    """Normalização para comparação de descrição (regra 1). A partir de
    28/09/2026 delega para classificacao_scm.normalizar_termo (mesma
    função usada em signals.py/db_writer.py para classificar sinais e
    timeline) — também remove preposições/artigos curtos, não só
    acento/pontuação, pelo mesmo motivo documentado lá: o nome oficial de
    um tipo de evento no dicionário do SCM nem sempre inclui "de"/"da"
    onde a redação livre incluiria, e essa inconsistência não pode virar
    uma falsa diferença de identidade entre dois atos do mesmo tipo."""
    return clsf.normalizar_termo(texto)


def chave_ato(processo: str, descricao: str, data_evento: str) -> str:
    """Regra 1: identidade do ATO individual (não do caso consolidado)."""
    norm = normalizar_descricao(descricao)
    return hashlib.sha256(f"{processo}|{norm}|{data_evento}".encode("utf-8")).hexdigest()


# Famílias de atos complementares que devem consolidar no MESMO caso
# editorial mesmo com descrições distintas (regra 4). Cada lista é um
# grupo — se dois atos do mesmo processo caem em listas diferentes do
# mesmo grupo, é o mesmo caso.
FAMILIAS_COMPLEMENTARES = [
    {"instauracao de decaimento", "intimacao para defesa", "decisao de decaimento"},
    {"instauracao de caducidade", "intimacao para defesa", "decisao de caducidade"},
    # OBS: propositalmente não há entrada genérica de "cessão" aqui — um
    # termo tão comum bateria com o cenário cross-processo da Kinross
    # (M9A-A05: dois PROCESSOS diferentes da mesma cessão, que precisam
    # cair na regra 3 sem processo na chave, não na regra 4 com processo
    # na chave). Termos de família precisam ser específicos o bastante
    # para não colidir com regra 3.
]


def familia_de(descricao_normalizada: str) -> Optional[frozenset]:
    """`descricao_normalizada` já passou por normalizar_descricao(). Os
    termos de FAMILIAS_COMPLEMENTARES também precisam passar pela mesma
    normalização antes da comparação (achado de 28/09/2026: sem isso,
    "instauracao de decaimento" — com "de" — nunca bate contra um texto já
    normalizado que teve o "de" removido; ver classificacao_scm.py)."""
    for familia in FAMILIAS_COMPLEMENTARES:
        for termo in familia:
            if clsf.normalizar_termo(termo) in descricao_normalizada:
                return frozenset(familia)
    return None


@dataclass
class Ato:
    processo: str
    descricao: str  # = DSEvento (nome do dicionário Evento.txt) — usar SÓ isto para classificação/identidade
    data_evento: str
    empresa: Optional[str] = None
    substancia: Optional[str] = None
    municipio: Optional[str] = None
    # Campos adicionados em 28/09/2026 (achado da auditoria do caso 830.649/2020):
    id_tipo_evento: Optional[int] = None       # IDEvento (FK pro dicionário Evento.txt)
    texto_narrativo: Optional[str] = None      # OBEvento/DSPublicacaoDOU — só para evidência/trecho_literal, nunca classificação
    area_ha: Optional[float] = None            # Processo.txt.QTAreaHA — liga dimensao_objetiva (ver signals.py)


# ----------------------------------------------------------------------------
# Regra 4b (28/09/2026) — sequência processual do MESMO instrumento
# administrativo (guia/portaria/alvará), reconhecida pelo número do
# instrumento no texto do ato, não por família de palavra-chave nem por
# coincidência de data. Genérico: qualquer processo/instrumento cujo texto
# siga o padrão "Nº NNN/AAAA" da ANM é reconhecido, não só guia de
# utilização e não só este processo.
#
# Deliberadamente exige o marcador "Nº/N°/N.º" explícito antes do número —
# isso distingue "Guia n° 61/2023" (o instrumento sendo referenciado/
# afetado pelo ato) de "GU - 405/2026" (o número do PRÓPRIO documento/
# despacho que registra o ato, que aparece sem esse marcador nos textos
# observados) — testado contra os dois textos reais do caso 830.649/2020
# (ver ETAPA3_PLANO_ESCRITA_REPROCESSAMENTO). Sem essa distinção, o regex
# agruparia pelo número errado.
_PADRAO_INSTRUMENTO = re.compile(r"N[ºO°]\.?\s*(\d{1,5})\s*/\s*(\d{4})", re.IGNORECASE)


def extrair_identificador_instrumento(texto: Optional[str]) -> Optional[str]:
    """Extrai um identificador estável 'NNN/AAAA' do texto narrativo de um
    ato (ato.texto_narrativo — NUNCA ato.descricao, que é o nome genérico
    do dicionário e não carrega o número do instrumento). Retorna None
    quando o padrão "Nº NNN/AAAA" não aparece no texto."""
    if not texto:
        return None
    m = _PADRAO_INSTRUMENTO.search(texto)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def chave_caso_editorial(ato: Ato) -> str:
    """Regras 3+4(+4b): chave do CASO consolidado.

    Regra 4 (família complementar, ex.: instauração de decaimento +
    intimação para defesa do MESMO processo) usa processo + família —
    processo entra na chave porque a família só faz sentido dentro do
    mesmo processo.

    Regra 4b (28/09/2026): quando o texto narrativo do ato referencia um
    número de instrumento (Nº NNN/AAAA — ver extrair_identificador_
    instrumento), agrupa por processo + esse instrumento. Isso é o que
    permite emissão (2023) e prorrogação (2026) da MESMA guia caírem no
    mesmo caso mesmo tendo datas diferentes e não pertencendo a nenhuma
    família de palavra-chave da regra 4. Checado antes da regra 3 porque é
    uma identidade mais específica (mesmo instrumento) do que a
    coincidência genérica de empresa/data/substância/geografia.

    Regra 3 (mesma empresa+data+substância+geografia formando uma decisão
    editorial única) NÃO inclui processo na chave — carta M9A-A05 exige
    explicitamente agrupar DOIS PROCESSOS DIFERENTES da Kinross (cessão
    conjunta, mesma empresa/data/substância/geografia) em um único caso.
    Incluir processo aqui quebraria esse teste de aceitação."""
    norm = normalizar_descricao(ato.descricao)
    familia = familia_de(norm)
    if familia:
        chave_familia = "|".join(sorted(familia))
        return hashlib.sha256(f"{ato.processo}|familia:{chave_familia}".encode("utf-8")).hexdigest()

    instrumento = extrair_identificador_instrumento(ato.texto_narrativo)
    if instrumento:
        return hashlib.sha256(f"{ato.processo}|instrumento:{instrumento}".encode("utf-8")).hexdigest()

    # sem família nem instrumento reconhecido: regra 3, cruza processo quando o resto bate
    return hashlib.sha256(
        f"{ato.empresa}|{ato.data_evento}|{ato.substancia}|{ato.municipio}".encode("utf-8")
    ).hexdigest()


def buscar_processos_por_titular_no_universo(atos_universo: List[Ato], titular: Optional[str],
                                              processo_atual: str) -> List[str]:
    """Checklist pergunta 11 ('histórico relevante') — busca de
    antecedentes no UNIVERSO INGERIDO desta rodada (todo `atos_universo`
    passado por main.run(), não só os atos que acabaram formando o caso
    atual, e não só os eventos que já existem no Editorial — achado de
    28/09/2026: a versão anterior só consultava `events`, ou seja, só
    achava antecedente se ele já tivesse sido processado e publicado
    antes; um processo antecedente do mesmo titular que estivesse no
    arquivo do SCM mas nunca tivesse virado evento editorial não era
    encontrado). Critério: mesmo texto de titular, processo diferente do
    atual — mesmo critério fraco (texto, não CNPJ estruturado) já
    documentado como limitação em db_writer.buscar_antecedentes_m9a,
    porque `Ato` não carrega CNPJ por linha (só o texto do titular vindo
    da ingestão). Retorna processos únicos, não atos."""
    if not titular:
        return []
    return sorted({
        ato.processo for ato in atos_universo
        if ato.empresa == titular and ato.processo != processo_atual
    })


def consolidar_atos(atos: List[Ato]) -> dict:
    """Regra 5: agrupa atos em casos editoriais, mantendo a lista de atos
    individuais por caso (destino: timeline_processual) separada da
    contagem editorial (destino: 1 linha em events por caso)."""
    casos: dict = {}
    for ato in atos:
        chave = chave_caso_editorial(ato)
        casos.setdefault(chave, []).append(ato)
    return casos


CAMPOS_MATERIAIS = {"titular", "situacao", "decisao", "area", "substancia", "prazo", "efeito"}


def houve_alteracao_material(valores_anteriores: dict, valores_novos: dict) -> bool:
    """Regra 6: só os 7 campos materiais listados disparam nova versão."""
    for campo in CAMPOS_MATERIAIS:
        if valores_anteriores.get(campo) != valores_novos.get(campo):
            return True
    return False
