"""
Módulo 6 (Outorgas de Recursos Hídricos do IGAM) — classificação semântica
de atos e filtro barato de vínculo mineral.

Duas responsabilidades, ambas da "Regra semântica obrigatória" da Carta
Operacional M6 v0.8 §23 e reforçadas pela Carta de Homologação M6-V1.0 §3:

  1. `classificar_ato()` — decide o tipo_evento_normalizado de um ato A
     PARTIR DO VERBO E DISPOSITIVO DECISÓRIO, nunca do título do arquivo,
     cabeçalho do documento ou nome da empresa. A própria carta de
     homologação dá o caso que prova por que isso importa: os arquivos de
     22 e 23/09/2026 usam a palavra "Cancelamentos" no cabeçalho, mas
     nenhum dos cinco atos é um cancelamento — os verbos operativos são
     "fica mantido o indeferimento" e "fica mantido o arquivamento". A
     precedência exigida (carta §23) é: verbo e dispositivo decisório do
     ato individual > conteúdo e resultado do ato > subtítulo interno >
     cabeçalho do documento > categoria do repositório > nome do arquivo.

  2. `tem_vinculo_mineral()` — o "filtro barato": decide, ANTES de
     qualquer chamada cara de IA, se um ato pertence ao núcleo editorial
     mineral ou deve ser descartado (carta de homologação, critério
     M6 A08: "os quatro casos evidentemente não minerais são eliminados
     antes da chamada cara de IA"). É igualmente um filtro por EVIDÊNCIA
     textual (finalidade, atividade, substância), nunca por nome de
     empresa/município — a carta M6 v0.8 §44 é explícita: "nunca afirmar
     relação [...] apenas porque pertencem à mesma empresa ou ao mesmo
     complexo", e "mesmo que ocorra em município minerador" não basta.

Nenhuma das duas funções toca banco nem rede — é lógica pura, testável
sem Supabase e sem os documentos reais do IGAM (ver test_signals.py).
"""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional


def _normalizar(texto: str) -> str:
    if not texto:
        return ""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return t.lower()


# ----------------------------------------------------------------------------
# 1) Classificação por verbo decisório (carta M6 v0.8 §23, tabela de
#    precedência). A ordem desta lista IMPORTA: expressões mais específicas
#    (ex. "fica mantido o indeferimento") vêm antes de termos genéricos
#    (ex. "indeferimento" sozinho), para nunca classificar uma MANUTENÇÃO
#    como se fosse a decisão original.
# ----------------------------------------------------------------------------
_REGRAS_VERBO = [
    # (padrão regex já normalizado, tipo_evento_normalizado)
    (r"fica mantid[oa] o indeferimento|mant[eê]m.{0,20}indeferimento", "manutencao_indeferimento"),
    (r"fica mantid[oa] o arquivamento|mant[eê]m.{0,20}arquivamento", "manutencao_arquivamento"),
    (r"anula.{0,30}arquivamento", "anulacao_arquivamento"),
    (r"onde se l[eê]|leia-se", "retificacao"),
    (r"\bautoriza\b|\bdefere\b", "concessao_outorga"),
    (r"ren[uú]ncia.{0,20}cancelamento|cancelamento.{0,20}ren[uú]ncia", "cancelamento_por_renuncia"),
    (r"\bcancela(do)?\b.{0,20}arquivamento", "cancelamento_de_arquivamento"),
    (r"\bsuspende\b|\bsuspens[aã]o\b", "suspensao"),
    (r"\brevoga\b|\brevoga[cç][aã]o\b", "revogacao"),
    (r"\banula\b|\banula[cç][aã]o\b", "anulacao"),
    (r"\bcassa\b|\bcassa[cç][aã]o\b", "cassacao"),
    (r"\bindefer", "indeferimento_original"),
    (r"\barquiv", "arquivamento_original"),
    # Particípios e infinitivos que aparecem nas publicações reais do IGAM (10/10/2026). Ficam NO FIM da lista:
    # nenhuma classificação já homologada acima muda; só deixam de cair em 'indeterminado' verbos escritos assim.
    (r"\banulad[oa]\b", "anulacao"),
    (r"\brevogad[oa]\b", "revogacao"),
    (r"\bcassad[oa]\b", "cassacao"),
    (r"\bautorizar\b|\bdeferid[oa]\b", "concessao_outorga"),
]


def classificar_ato(trecho_literal: str) -> str:
    """Retorna o tipo_evento_normalizado a partir do verbo/dispositivo
    decisório LITERAL do trecho do ato — nunca do título do arquivo, nem
    do cabeçalho do documento. Quem chama esta função decide, por conta
    própria, qual trecho é "o verbo decisório do ato individual" (em
    geral a frase operativa da decisão, não o preâmbulo nem a ementa).

    Retorna 'indeterminado' se nenhum padrão bater — isso deve forçar
    revisão humana, nunca um default silencioso para 'cancelamento' ou
    qualquer outro valor (carta: "elementos posteriores nunca podem
    prevalecer sobre o verbo decisório expresso" — se o verbo não foi
    identificado, não há elemento posterior que o substitua)."""
    t = _normalizar(trecho_literal)
    for padrao, tipo in _REGRAS_VERBO:
        if re.search(padrao, t):
            return tipo
    return "indeterminado"


# ----------------------------------------------------------------------------
# 2) Filtro barato de vínculo mineral (carta M6 v0.8 §44.9, trava do
#    critério M6 A08). Termos de evidência positiva (vínculo mineral
#    provável) e termos de evidência negativa (finalidade claramente não
#    mineral) — nenhum dos dois é fechado por desenho; ajustar conforme
#    novos lotes revelarem vocabulário novo (mesma postura do M9A em
#    relação à amostra do dicionário do SCM).
# ----------------------------------------------------------------------------
_TERMOS_MINERAL = [
    "minerio", "mineracao", "mina", "lavra", "beneficiamento", "barragem de rejeito",
    "rejeito", "minerario", "anm", "pesquisa mineral", "extracao mineral",
    "minerodutos", "pelotizacao", "usina de pelotizacao",
]

_TERMOS_NAO_MINERAL_EXPLICITO = [
    "irrigacao", "consumo humano", "consumo animal", "dessedentacao",
    "agroindustria", "agricola", "agropecuaria", "lazer", "turismo",
    "saneamento", "esgoto", "abastecimento publico", "piscicultura",
    "lavagem de veiculos", "limpeza",
]


@dataclass
class SinaisVinculoMineral:
    titular: str = ""
    finalidade_uso: str = ""
    atividade_associada: str = ""
    texto_livre: str = ""


VINCULO_CONFIRMADO = "confirmado"
VINCULO_NAO_MINERAL_CONFIRMADO = "nao_mineral_confirmado"
VINCULO_INDETERMINADO = "indeterminado"


def tem_vinculo_mineral(sinais: SinaisVinculoMineral) -> tuple:
    """Retorna (status, motivo). `status` é um de três valores, NÃO um
    booleano — a Carta de Homologação M6-V1.0 dá um caso (Codemig, §5)
    que é justamente a diferença entre os dois "não": o nome é um sinal,
    mas a finalidade/atividade mineral não está comprovada nem refutada,
    e o caso "permanece em revisão controlada, sem score editorial
    positivo e sem pré-release" — isto é diferente de Plascar/Alan Alves/
    Associação Versailles/Unimed BH, onde a finalidade documentada é
    EXPLICITAMENTE não-mineral (critério M6 A08: esses sim são
    eliminados, Codemig não é "eliminado", fica em apuração).

      - VINCULO_CONFIRMADO: finalidade/atividade documentada contém
        termo de vínculo mineral -> processa normalmente (scoring).
      - VINCULO_NAO_MINERAL_CONFIRMADO: finalidade/atividade documentada
        é explicitamente não-mineral -> descartado antes da IA (M6 A08).
      - VINCULO_INDETERMINADO: nenhuma evidência textual de vínculo
        mineral nem de não-vínculo -> fica em apuração (status
        'em_apuracao', não 'descartado'), igual ao caso Codemig.

    Regra de precedência: finalidade/atividade documentada decide; nome
    da empresa, município ou tamanho do documento NUNCA decidem por si
    só (carta M6 v0.8 §44.9 e §43.4 — "nome conhecido, sozinho, não
    produz A"; "mesmo que ocorra em município minerador")."""
    corpo = _normalizar(" ".join([
        sinais.finalidade_uso, sinais.atividade_associada, sinais.texto_livre
    ]))

    # "mina" só vale como palavra inteira: como pedaço de palavra casaria com "determina", "Minas Gerais",
    # "mineiro" e daria vínculo mineral por acidente (a carta exige evidência de finalidade/atividade).
    if any(re.search(r"\bmina\b", corpo) if termo == "mina" else termo in corpo for termo in _TERMOS_MINERAL):
        return VINCULO_CONFIRMADO, "finalidade/atividade documentada contém termo de vínculo mineral"

    if any(termo in corpo for termo in _TERMOS_NAO_MINERAL_EXPLICITO):
        return VINCULO_NAO_MINERAL_CONFIRMADO, "finalidade/atividade documentada é explicitamente não-mineral"

    return VINCULO_INDETERMINADO, "nenhuma evidência textual de vínculo mineral na finalidade/atividade (ausência de prova, não prova de ausência — exige apuração humana, não é descarte)"


# ----------------------------------------------------------------------------
# Travas semânticas de score (carta M6 v0.8 §43.5) — não decidem SE o ato é
# mineral (isso é tem_vinculo_mineral), decidem se um score alto é
# sustentável. Usadas por scoring.py.
# ----------------------------------------------------------------------------
@dataclass
class SinaisScoreM6:
    permite_restringe_interrompe_operacao: bool = False     # consequência operacional
    vazao_volume_area_documentados: bool = False            # dimensão hídrica
    escassez_conflito_dano_comunidade: bool = False          # risco/conflito
    materialidade_concessao_indeferimento_cancelamento: bool = False  # materialidade
    fato_novo_prazo_vencimento_mudanca_recente: bool = False  # novidade/sinal temporal
    cruzamento_licenca_tac_auto_recorrencia: bool = False     # cruzamentos/histórico
    empresa_relevante_porte_centralidade: bool = False        # relevância empresa
    angulo_pouco_percebido: bool = False                      # potencial exclusividade

    # Travas (reduzem/zeram, nunca aumentam):
    vinculo_apenas_presumido: bool = False       # trava de B
    parecer_sem_decisao_ou_recurso_pendente: bool = False  # trava de A
    retificacao_puramente_cadastral: bool = False  # redutor
    registro_antigo_sem_fato_novo: bool = False     # redutor
