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
  5. Manter os atos individuais na Timeline_Processual, mas contar apenas
     um caso em Editorial.
  6. Criar nova versão quando houver alteração material (titular, situação,
     decisão, área, substância, prazo ou efeito).

Esta lógica de chaves é pura (não depende de rede) e por isso é a parte
mais confiável do coletor M9A — testada em test_consolidacao.py com dados
sintéticos que reproduzem os 5 casos de controle da carta (§11), sem
precisar da amostra real do SCM.
"""
import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional


def normalizar_descricao(texto: str) -> str:
    """Normalização simples para comparação de descrição (regra 1):
    minúsculas, sem acento, sem espaço duplicado/pontuação."""
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


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
    for familia in FAMILIAS_COMPLEMENTARES:
        for termo in familia:
            if termo in descricao_normalizada:
                return frozenset(familia)
    return None


@dataclass
class Ato:
    processo: str
    descricao: str
    data_evento: str
    empresa: Optional[str] = None
    substancia: Optional[str] = None
    municipio: Optional[str] = None


def chave_caso_editorial(ato: Ato) -> str:
    """Regras 3+4: chave do CASO consolidado.

    Regra 4 (família complementar, ex.: instauração de decaimento +
    intimação para defesa do MESMO processo) usa processo + família —
    processo entra na chave porque a família só faz sentido dentro do
    mesmo processo.

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
    # sem família reconhecida: regra 3, cruza processo quando o resto bate
    return hashlib.sha256(
        f"{ato.empresa}|{ato.data_evento}|{ato.substancia}|{ato.municipio}".encode("utf-8")
    ).hexdigest()


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
