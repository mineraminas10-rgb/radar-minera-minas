"""
Módulo 9A — ingestão dos microdados SCM (ANM) + filtro de recorte
(Carta M9A §2, §3, §16 ordem de implementação passo 1).

AVISO — leia antes de rodar contra a fonte real: este arquivo é o que tem
MAIOR incerteza de todo o pacote M9A. Não consegui acessar
dadosabertos.anm.gov.br a partir deste sandbox (bloqueio de rede,
confirmado em 23/09/2026) para ver o formato real dos arquivos de
microdados (nomes de coluna, separador, encoding, se vem em um arquivo só
ou particionado por UF/ano). O código abaixo assume um CSV com colunas
nomeadas de forma razoável (baseadas no vocabulário da própria carta:
processo, uf, municipio, substancia, fase, evento_tipo, data_evento,
titular etc.) — isso é uma SUPOSIÇÃO, não um fato verificado. Ajustar
`COLUNAS_ESPERADAS` e `carregar_microdados_scm()` assim que a Rapha
mandar uma amostra real (ela confirmou que vai enviar).

O que ESTÁ testável sem a amostra real: a lógica de exclusão de família
(§2 "fora do M9A") e de recorte por presença territorial em MG, desde que
alimentadas com um DataFrame no formato esperado — ver test_ingestao.py.
"""
import pandas as pd
from typing import Optional

# TODO (pendente de amostra real): confirmar nomes de coluna reais do SCM.
COLUNAS_ESPERADAS = [
    "processo", "uf", "municipio", "substancia", "fase", "evento_tipo",
    "data_evento", "titular", "area_ha",
]

# Carta §2 "Fora do M9A": barragens, autos de infração, multas, CFEM, água
# mineral, fiscalização genérica e outras famílias já cobertas por módulos
# próprios não entram na pontuação do 9A.
FAMILIAS_FORA_DO_ESCOPO = [
    "barragem", "auto de infração", "auto de infracao", "multa", "cfem",
    "água mineral", "agua mineral", "fiscalização", "fiscalizacao",
]

# Carta §2 "Incluir": atos materiais relevantes para o 9A.
EVENTOS_MATERIAIS_INCLUIDOS = [
    "concessão", "concessao", "cessão", "cessao", "renúncia", "renuncia",
    "caducidade", "decaimento", "interdição de lavra", "interdicao de lavra",
    "penhora", "indisponibilidade", "guia de utilização", "guia de utilizacao",
    "avanço de pesquisa", "avanco de pesquisa", "nova substância",
    "nova substancia", "reavaliação de reserva", "reavaliacao de reserva",
]


def carregar_microdados_scm(caminho_arquivo: str) -> pd.DataFrame:
    """Carrega o arquivo de microdados baixado do SCM. TODO: confirmar
    separador/encoding reais (chutando ';' e 'latin-1', comuns em dados
    abertos de órgãos públicos brasileiros, mas não verificado)."""
    df = pd.read_csv(caminho_arquivo, sep=";", encoding="latin-1", dtype=str)
    faltando = set(COLUNAS_ESPERADAS) - set(df.columns)
    if faltando:
        raise ValueError(
            f"Colunas esperadas ausentes no arquivo SCM: {faltando}. "
            "O formato real provavelmente diverge da suposição em COLUNAS_ESPERADAS "
            "— ajustar este arquivo contra uma amostra real antes de prosseguir."
        )
    return df


def filtrar_presenca_mg(df: pd.DataFrame) -> pd.DataFrame:
    """Carta §2: monitorar processos com presença territorial em MG, mesmo
    quando a sede da empresa está em outro estado — por isso filtra por
    UF do processo/município, não por UF da empresa."""
    return df[df["uf"].str.upper() == "MG"].copy()


def excluir_familias_fora_do_escopo(df: pd.DataFrame) -> pd.DataFrame:
    padrao = "|".join(FAMILIAS_FORA_DO_ESCOPO)
    mascara_fora = df["evento_tipo"].str.lower().str.contains(padrao, na=False, regex=True)
    return df[~mascara_fora].copy()


def eh_evento_material(descricao_evento: str) -> bool:
    """Carta §2/§6: só atos materiais entram na pontuação — protocolo,
    juntada e documento diverso ficam de fora (viram 'rotina' no score,
    não são descartados aqui, só marcados)."""
    d = (descricao_evento or "").lower()
    return any(padrao in d for padrao in EVENTOS_MATERIAIS_INCLUIDOS)


def aplicar_recorte_m9a(df: pd.DataFrame) -> pd.DataFrame:
    """Pipeline completo do recorte (carta §2, calibração v0.2 §4):
    presença em MG -> exclusão de famílias fora do escopo. Retorna o
    universo dentro do recorte M9A (equivalente aos 4.955 eventos da
    calibração v0.2, ainda sem consolidação editorial)."""
    df_mg = filtrar_presenca_mg(df)
    df_recorte = excluir_familias_fora_do_escopo(df_mg)
    return df_recorte
